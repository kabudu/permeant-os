**PermeantOS Implementation Plan v1.1**  
**Unified State Exchange Format (USXF) & State-Fluid Hypervisor for Migratory AI Agents**  
**Date:** June 13, 2026  
**Version:** 1.1 (Incorporates full independent technical review feedback dated June 13, 2026)

### 1. Executive Summary & Updated Vision

PermeantOS is a **state-fluid hypervisor** enabling long-running AI agents to migrate live KV cache (and eventually full agent state) across heterogeneous hardware and frameworks without expensive re-prefill.

**USXF v1.1** is the open interchange format: versioned JSON metadata + Safetensors payload, now with explicit support for GQA/MLA, chat template state, content-addressable blocks, and strong integrity/confidentiality guarantees.

**Major updates in v1.1** (addressing independent technical review):

- Injection architecture now centers on the production-grade `KVConnectorBase_V1` API (or LMCache multiprocess mode) rather than generic LMCache/APC tricks.
- Numerical equivalence treated realistically: BF16 recommended as default canonical exchange format; divergence curves measured; “exact continuation” is an aspiration.
- Wire format (streaming) separated from at-rest format (Safetensors).
- Security strengthened with encrypt-then-sign and header protection.
- Prominent prior-art section with clear differentiation (cross-hardware + agent-centric).
- Added `mla_spec`, `chat_state`, formal state machine, per-phase timeouts, break-even analysis, and ResourcePolicy.
- Timeline adjusted with Phase 0.5 injection feasibility spike.
- PegaFlow studied as primary architectural reference.

**Success Metrics (MVP / Phase 1)**:

- Successful KV cache injection via custom `KVConnectorBase_V1` plugin with verified continuation on Llama-3.1-style GQA models.
- Post-migration generation matches local continuation within configurable tolerance (measured via divergence curves over 128+ tokens).
- Migration faster than re-prefill for contexts ≥32k at ≥25 Gbps networks (with FP8 transfer quantization).
- Zero corruption or desync on committed handovers.

### 2. High-Level Architecture (v1.1)

```
┌─────────────────────────────────────────────────────────────────────┐
│                      PermeantOS Hypervisor (v1.1)                    │
├─────────────────────────────────────────────────────────────────────┤
│  Python SDK + Agent Memory Graph hooks                               │
│  Orchestrator (placement, warm-start decision, two-phase commit)     │
├─────────────────────────────────────────────────────────────────────┤
│  USXF v1.1 Core                                                      │
│  ├── Metadata (versioned JSON + CapabilityExchange)                  │
│  ├── Payload (Safetensors at-rest; gRPC/NIXL wire)                   │
│  └── Integrity (encrypt-then-sign, per-chunk CRC32, signatures)      │
├─────────────────────────────────────────────────────────────────────┤
│  Backend Modules                                                     │
│  ├── Extractor: candle-llama (Metal) — safe copy + optional unsafe   │
│  │             zero-copy Metal path                                  │
│  ├── Transpiler: layout reshape, quant/precision conversion          │
│  └── Injector: Custom KVConnectorBase_V1 plugin (preferred)          │
│                or LMCache MP mode writer                             │
├─────────────────────────────────────────────────────────────────────┤
│  Transport                                                           │
│  └── gRPC (tonic) layerwise streaming + optional NIXL (RDMA)         │
├─────────────────────────────────────────────────────────────────────┤
│  Security & Policy                                                   │
│  └── mTLS + Ed25519, encrypt-then-sign, ResourcePolicy (quotas)      │
└─────────────────────────────────────────────────────────────────────┘
```

**Key Principle**: PermeantOS complements existing systems (LMCache, PegaFlow, NIXL, Mooncake) by providing the **cross-hardware (Metal ↔ CUDA) and agent-centric** layer with a universal interchange format.

### 3. USXF Specification v1.1 (Key Changes)

**Wire Format**: gRPC streaming messages (per-layer or per-block tensors) + optional NIXL for RDMA.  
**At-Rest Format**: Safetensors (for snapshots/checkpoints only).

**Updated Metadata Header** (additions in **bold**):

```json
{
  "usxf_version": "1.1",
  "model_architecture": "Llama-3.1-8B-Instruct",
  "model_identity": {                    // clarified
    "config_hash": "sha256:...",         // architecture params only
    "weights_revision": "hf:meta-llama/Llama-3.1-8B-Instruct@main"
  },
  "attention_type": "gqa",
  "model_cache_spec": { ... },           // same as v1.0
  "mla_spec": {                          // NEW - even if unused in Phase 1
    "latent_dim": 512,
    "rope_head_dim": 64,
    "nope_head_dim": 128,
    "kv_lora_rank": 512
  },
  "chat_state": {                        // NEW
    "template_name": "llama-3.1-instruct",
    "template_hash": "sha256:...",
    "turn_boundaries": [0, 142, 890, 1024],
    "roles": ["system", "user", "assistant", "user"]
  },
  "token_ids": [...],
  "seq_len": 10421,
  "batch_size": 1,                       // v1.0 = single-sequence only
  "dtype": "bfloat16",                   // RECOMMENDED default (was fp16)
  "source_quantization": { ... },
  "transfer_quantization": {             // encouraged for bandwidth
    "scheme": "fp8",
    "scale": 0.1234
  },
  "block_size": 256,
  "block_hashes": ["sha256:...", ...],
  "position_ids": [...],                 // optional
  "extra": {},
  "created_at": "...",
  "extractor_id": "...",
  "checksum": "sha256:...",
  "signature": "ed25519:..."
}
```

**Safetensors Payload Keys**:

- GQA/MHA: `layer.{i}.key`, `layer.{i}.value`
- MLA: `layer.{i}.kv_latent`, `layer.{i}.rope_key` (plus `nope` components as needed)

### 4. Core Components & Tech Stack (Updated)

**Rust crates** remain similar, with new emphasis:

- `kvconnector-plugin/`: Implementation of `KVConnectorBase_V1` (or LMCache MP writer).
- `transpiler/`: Critical component — converts canonical USXF layout to vLLM’s `[num_blocks, num_kv_heads, head_dim, block_size]` (K and V separate).

**Primary Reference Implementation**: Study **PegaFlow** (Rust core + vLLM `PegaKVConnector`) in detail during Phase 0.

**Python SDK**: Elevated `attach_agent_memory()` for future first-class Agent Memory Graph support.

### 5. Migration Pipeline (v1.1 — KVConnector-Centric)

1. **Trigger** + **CapabilityExchange** (source/target negotiate model identity, attention type, precision, seq_len limits, block size).
2. **Warm-Start Decision** (new): If `estimated_transfer_time > estimated_prefill_time × 0.7`, recommend re-prefill instead.
3. **Extraction** (Candle): Read `Cache` tensors → CPU (safe path by default; advanced Metal zero-copy optional).
4. **Transpilation**: Reshape + precision/quant conversion to target layout.
5. **Streaming** (gRPC or NIXL): Layerwise / blockwise with per-chunk CRC32.
6. **Injection** (target):
   - Preferred: Custom `KVConnectorBase_V1` plugin receives tensors and registers them directly into vLLM’s KV manager.
   - Alternative: Write USXF blocks into LMCache storage format (MP daemon mode).
7. **Validation Harness**: Generate N tokens; compute divergence curve (logit delta over time). Configurable tolerance + auto-fallback.
8. **Two-Phase Commit** with formal state machine:
   - `IDLE → EXTRACTING → STREAMING → INJECTING → VALIDATING → COMMITTED | ROLLED_BACK`
9. **Cleanup** + provenance update (for multi-hop).

**Per-phase timeouts** and resource quotas enforced via `ResourcePolicy`.

### 6. Security Architecture (Strengthened)

- **Encrypt-then-Sign**: Entire packet (header + payload) encrypted (AES-GCM), then signed. `token_ids` never travels in cleartext.
- **mTLS + Ed25519** mandatory.
- **Key Management**: Phase 1 = pre-shared keys in config. Phase 2+ = SPIFFE/SPIRE-style workload identity with short-lived certs.
- **ResourcePolicy** (new): Max concurrent migrations, memory quota per source/agent, exponential backoff on failures, circuit breaker.
- **Audit & Rate Limiting**: Structured events + per-daemon rate limits.

### 7. Performance & Realism (New Analysis)

**Break-even Guidance** (example for Llama-3.1-8B, FP16/BF16):

- 16k context ≈ 2 GB KV cache.
- At 10 Gbps: transfer ~1.6 s (plus overhead) vs ~0.8–1.5 s prefill → often better to re-prefill.
- At 25+ Gbps + FP8 transfer quantization: migration wins at ≥32k context.
- Real value emerges at 64k–128k+ contexts (transfer linear, prefill quadratic/super-linear in attention).

**30% target** now qualified: “< 30% of prefill time for ≥32k context at ≥25 Gbps with FP8 transfer quantization.”

**Format Separation** (critical fix): gRPC/NIXL for live migration streaming; Safetensors only for persistent snapshots.

### 8. Prior Art & Competitive Positioning (New Dedicated Section)

**Production Systems Referenced**:

- **LMCache** + `KVConnectorBase_V1` — tiered storage, 256-token chunks, CacheGen compression.
- **PegaFlow** — closest architectural analog (Rust core, sidecar, vLLM connector). Primary reference for injector design.
- **NVIDIA NIXL** — production-ready RDMA/UCX transport (use directly instead of custom gRPC where possible).
- **llm-d**, **Mooncake**, **MemServe** — KV-aware routing and disaggregation.
- **CacheGen** (integrated in LMCache), **CacheBlend** — compression and non-exact prefix reuse.

**PermeantOS Differentiation** (emphasized):

- True cross-hardware migration (Apple Metal ↔ NVIDIA CUDA).
- Agent-centric framing + future full Agent Memory Graph migration.
- Open, framework-agnostic interchange format (USXF).

PermeantOS is the **cross-hardware complement** to these mostly single-framework or intra-cluster systems.

### 9. Robustness Enhancements

- Formal migration state machine + per-phase timeouts + CRC32 per chunk.
- Prompt-hash deduplication (future): only transfer user-specific KV deltas when system prompt is already cached on target.
- Multi-hop provenance chain (each hop signs; full chain in header).
- Speculative migration (future): begin streaming opportunistically before final decision.
- Comprehensive numerical validation harness with divergence curves.

### 10. Implementation Roadmap (Adjusted)

**Phase 0 – Foundations & De-Risking (Weeks 1–4)**

- USXF v1.1 schema + Rust core (metadata, signing, encrypt-then-sign).
- Study PegaFlow + `KVConnectorBase_V1` in depth.
- **Phase 0.5 Spike (critical)**: Minimal KVConnector plugin that injects externally-created tensors (correct vLLM layout) and validates continuation generation. This is now a feasibility validation, not research.

**Phase 1 – Core Cross-Framework Migration (Weeks 5–10)**

- Candle extractor (safe path) + transpiler for GQA.
- Full `KVConnectorBase_V1` injector (or LMCache MP writer).
- End-to-end Llama-3.1 GQA migration (Metal → CUDA) with validation harness.
- Basic Python SDK + warm-start decision logic.
- Security baseline (mTLS + encrypt-then-sign + ResourcePolicy).

**Phase 2 – Hardening & Performance (Weeks 11–15)**

- FP8 transfer quantization + break-even logic.
- NIXL integration option.
- Observability, formal state machine, per-phase timeouts.
- Numerical divergence curve analysis across hardware.
- Multi-sequence considerations (design only; v1.0 remains single-sequence).

**Phase 3 – Extensibility (Weeks 16–20)**

- MLA support (`mla_spec` + latent handling).
- `chat_state` enforcement.
- Agent Memory Graph (first-class section in USXF).
- Additional backends and bidirectional flows.

**Phase 4 – Ecosystem Release (Weeks 21–26)**

- Public release, documentation, paper, community onboarding.
- Multi-hop + speculative migration prototypes.

### 11. Risks & Mitigations (Updated)

- **Cross-framework numerical behavior**: BF16 default + divergence measurement + fallback.
- **Injection complexity**: Phase 0.5 spike + PegaFlow reference implementation.
- **Timeline slippage**: Explicit feasibility gate before full cross-framework work.
- **Adoption**: Strong Python SDK + clear positioning against existing systems.

### 12. Next Steps & Immediate Actions

1. Approve this v1.1 plan.
2. Begin Phase 0 + Phase 0.5 KVConnector injection prototype (highest priority).
3. Deep-dive PegaFlow codebase this week.
4. Decide canonical exchange dtype (recommend BF16 default).

This v1.1 plan is now significantly more grounded, realistic, and aligned with the current production ecosystem while preserving (and sharpening) PermeantOS’s unique value.

Would you like me to also produce:

- The detailed USXF v1.1 JSON Schema + Rust struct definitions?
- A minimal `KVConnectorBase_V1` plugin skeleton?
- Or the break-even analysis spreadsheet/model?

I’m ready to move into code or further documentation as soon as you give the word. This project is now on a much stronger footing.

**USXF v1.1 — Detailed JSON Schema + Rust Struct Definitions**

Below is the complete, production-ready specification for the **USXF v1.1 metadata header**.

### 1. USXF v1.1 JSON Schema (Draft 2020-12)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://permeant-os.dev/schemas/usxf/v1.1/header.json",
  "title": "USXF v1.1 Metadata Header",
  "type": "object",
  "required": [
    "usxf_version",
    "model_architecture",
    "model_identity",
    "attention_type",
    "model_cache_spec",
    "token_ids",
    "seq_len",
    "batch_size",
    "dtype",
    "block_size",
    "block_hashes",
    "created_at",
    "extractor_id",
    "checksum",
    "signature"
  ],
  "properties": {
    "usxf_version": {
      "type": "string",
      "const": "1.1",
      "description": "USXF format version. Must be exactly '1.1'."
    },
    "model_architecture": {
      "type": "string",
      "minLength": 1,
      "description": "Human-readable model name (e.g. 'Llama-3.1-8B-Instruct')"
    },
    "model_identity": {
      "$ref": "#/$defs/ModelIdentity"
    },
    "attention_type": {
      "type": "string",
      "enum": ["mha", "gqa", "mqa", "mla", "hybrid", "other"],
      "description": "Attention mechanism used by the model"
    },
    "model_cache_spec": {
      "$ref": "#/$defs/ModelCacheSpec"
    },
    "mla_spec": {
      "$ref": "#/$defs/MlaSpec",
      "description": "Required when attention_type == 'mla'. Ignored otherwise."
    },
    "chat_state": {
      "$ref": "#/$defs/ChatState",
      "description": "Optional but recommended for chat/instruct models"
    },
    "token_ids": {
      "type": "array",
      "items": { "type": "integer", "minimum": 0 },
      "minItems": 1,
      "description": "Full token history of the migrated context"
    },
    "seq_len": {
      "type": "integer",
      "minimum": 1
    },
    "batch_size": {
      "type": "integer",
      "const": 1,
      "description": "USXF v1.1 supports only single-sequence migration. Multi-sequence is planned for v1.2+."
    },
    "dtype": {
      "type": "string",
      "enum": ["float16", "bfloat16", "float32"],
      "default": "bfloat16",
      "description": "Canonical exchange precision. bfloat16 is strongly recommended."
    },
    "source_quantization": {
      "$ref": "#/$defs/QuantizationInfo"
    },
    "transfer_quantization": {
      "$ref": "#/$defs/QuantizationInfo",
      "description": "Quantization applied only for network transfer (dequantized on target)"
    },
    "block_size": {
      "type": "integer",
      "minimum": 1,
      "default": 256,
      "description": "Tokens per content-addressable block (aligned with LMCache/vLLM)"
    },
    "block_hashes": {
      "type": "array",
      "items": { "type": "string", "pattern": "^sha256:[a-f0-9]{64}$" },
      "description": "SHA-256 hash of each token block for content-addressable lookup"
    },
    "position_ids": {
      "type": "array",
      "items": { "type": "integer", "minimum": 0 },
      "description": "Optional explicit position IDs (if not derivable from token_ids)"
    },
    "extra": {
      "type": "object",
      "additionalProperties": true,
      "description": "Extensibility point for future fields or plugin data"
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    },
    "extractor_id": {
      "type": "string",
      "minLength": 1
    },
    "checksum": {
      "type": "string",
      "pattern": "^sha256:[a-f0-9]{64}$",
      "description": "SHA-256 of the Safetensors payload (after header)"
    },
    "signature": {
      "type": "string",
      "pattern": "^ed25519:[A-Za-z0-9+/=]+$",
      "description": "Ed25519 signature over the encrypted packet (encrypt-then-sign)"
    }
  },
  "$defs": {
    "ModelIdentity": {
      "type": "object",
      "required": ["config_hash", "weights_revision"],
      "properties": {
        "config_hash": {
          "type": "string",
          "pattern": "^sha256:[a-f0-9]{64}$",
          "description": "Hash of the model config (architecture parameters only)"
        },
        "weights_revision": {
          "type": "string",
          "description": "Hugging Face revision or semantic identifier (e.g. 'hf:meta-llama/Llama-3.1-8B-Instruct@main')"
        }
      }
    },
    "ModelCacheSpec": {
      "type": "object",
      "required": [
        "n_layers",
        "n_q_heads",
        "n_kv_heads",
        "head_dim",
        "hidden_size"
      ],
      "properties": {
        "n_layers": { "type": "integer", "minimum": 1 },
        "n_q_heads": { "type": "integer", "minimum": 1 },
        "n_kv_heads": { "type": "integer", "minimum": 1 },
        "head_dim": { "type": "integer", "minimum": 1 },
        "hidden_size": { "type": "integer", "minimum": 1 },
        "max_position_embeddings": { "type": "integer" },
        "rope_theta": { "type": "number" },
        "sliding_window": { "type": ["integer", "null"] }
      }
    },
    "MlaSpec": {
      "type": "object",
      "required": [
        "latent_dim",
        "rope_head_dim",
        "nope_head_dim",
        "kv_lora_rank"
      ],
      "properties": {
        "latent_dim": { "type": "integer" },
        "rope_head_dim": { "type": "integer" },
        "nope_head_dim": { "type": "integer" },
        "kv_lora_rank": { "type": "integer" }
      }
    },
    "ChatState": {
      "type": "object",
      "required": [
        "template_name",
        "template_hash",
        "turn_boundaries",
        "roles"
      ],
      "properties": {
        "template_name": { "type": "string" },
        "template_hash": {
          "type": "string",
          "pattern": "^sha256:[a-f0-9]{64}$"
        },
        "turn_boundaries": {
          "type": "array",
          "items": { "type": "integer", "minimum": 0 }
        },
        "roles": {
          "type": "array",
          "items": {
            "type": "string",
            "enum": ["system", "user", "assistant", "tool"]
          }
        }
      }
    },
    "QuantizationInfo": {
      "type": "object",
      "required": ["scheme"],
      "properties": {
        "scheme": {
          "type": "string",
          "enum": [
            "fp16",
            "bf16",
            "fp8",
            "int8",
            "q4_k_m",
            "awq",
            "gptq",
            "none"
          ]
        },
        "group_size": { "type": ["integer", "null"] },
        "scales": { "type": ["object", "null"] }
      }
    }
  },
  "additionalProperties": false
}
```

### 2. Rust Struct Definitions (Production Style)

```rust
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct UsxfHeader {
    pub usxf_version: String,                    // Must be "1.1"
    pub model_architecture: String,
    pub model_identity: ModelIdentity,
    pub attention_type: AttentionType,
    pub model_cache_spec: ModelCacheSpec,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mla_spec: Option<MlaSpec>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub chat_state: Option<ChatState>,
    pub token_ids: Vec<u32>,
    pub seq_len: usize,
    pub batch_size: u32,                         // Currently must be 1
    pub dtype: ExchangeDtype,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_quantization: Option<QuantizationInfo>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub transfer_quantization: Option<QuantizationInfo>,
    pub block_size: usize,
    pub block_hashes: Vec<String>,               // "sha256:..."
    #[serde(skip_serializing_if = "Option::is_none")]
    pub position_ids: Option<Vec<usize>>,
    #[serde(default)]
    pub extra: HashMap<String, serde_json::Value>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub extractor_id: String,
    pub checksum: String,                        // "sha256:..."
    pub signature: String,                       // "ed25519:..."
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AttentionType {
    Mha,
    Gqa,
    Mqa,
    Mla,
    Hybrid,
    Other,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExchangeDtype {
    Float16,
    Bfloat16,      // Recommended default
    Float32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelIdentity {
    pub config_hash: String,
    pub weights_revision: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelCacheSpec {
    pub n_layers: usize,
    pub n_q_heads: usize,
    pub n_kv_heads: usize,
    pub head_dim: usize,
    pub hidden_size: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_position_embeddings: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rope_theta: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sliding_window: Option<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MlaSpec {
    pub latent_dim: usize,
    pub rope_head_dim: usize,
    pub nope_head_dim: usize,
    pub kv_lora_rank: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatState {
    pub template_name: String,
    pub template_hash: String,
    pub turn_boundaries: Vec<usize>,
    pub roles: Vec<String>,                    // "system", "user", etc.
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QuantizationInfo {
    pub scheme: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group_size: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scales: Option<serde_json::Value>,
}

// Top-level packet wrapper (header + reference to Safetensors payload)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UsxfPacket {
    pub header: UsxfHeader,
    /// Path or in-memory reference to the Safetensors payload.
    /// In wire protocol this is sent separately via streaming.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub payload_path: Option<String>,
}
```

### 3. Example JSON Instance (Minimal Valid v1.1 Header)

```json
{
  "usxf_version": "1.1",
  "model_architecture": "Llama-3.1-8B-Instruct",
  "model_identity": {
    "config_hash": "sha256:7f8e9a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f",
    "weights_revision": "hf:meta-llama/Llama-3.1-8B-Instruct@main"
  },
  "attention_type": "gqa",
  "model_cache_spec": {
    "n_layers": 32,
    "n_q_heads": 32,
    "n_kv_heads": 8,
    "head_dim": 128,
    "hidden_size": 4096,
    "max_position_embeddings": 131072,
    "rope_theta": 500000.0,
    "sliding_window": null
  },
  "token_ids": [128000, 1043, 3421, 400, 2993],
  "seq_len": 5,
  "batch_size": 1,
  "dtype": "bfloat16",
  "block_size": 256,
  "block_hashes": ["sha256:abc123..."],
  "created_at": "2026-06-13T22:10:00Z",
  "extractor_id": "permeant-os-candle-v0.3.1",
  "checksum": "sha256:def4567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
  "signature": "ed25519:base64signaturehere..."
}
```

### Usage Notes

- **Wire Protocol**: The JSON header is sent first (encrypted + signed). Tensor data follows as separate gRPC messages (or NIXL buffers). Safetensors is **only** used for at-rest snapshots.
- **Validation**: Use the JSON Schema above for strict validation on both ends. The Rust structs provide ergonomic deserialization + type safety.
- **Extensibility**: Use the `extra` field or bump `usxf_version` for future changes. Never add required fields without a version bump.
- **Signature Scope**: The `signature` covers the **encrypted** (header + payload) envelope (encrypt-then-sign model).

Would you like me to also provide:

- The full gRPC `.proto` definition for the streaming wire protocol?
- A helper function to compute `block_hashes` and `checksum`?
- Validation logic (JSON Schema + custom Rust checks)?

Just say the word and I’ll generate the next piece.
