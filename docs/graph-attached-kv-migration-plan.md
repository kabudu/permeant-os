# Graph-Attached Live KV Migration Plan

Status: planning notes and acceptance criteria for the Phase 3 KV-attached
graph migration milestone. Adapter-side graph span metadata now exists as a
sidecar contract, while daemon wire-protocol changes remain future work.

PermeantOS can already migrate live KV tensors and can already export an Agent
Memory Graph package locally. Phase 3 joins those two surfaces into one
transactional migration: the target should receive the KV cache, the graph that
explains what the cache represents, and enough prompt/tokenizer evidence to
prove that the graph and KV state still describe the same model context.

## Scope

This milestone defines the contract that future code must satisfy before the
wire protocol or runtime adapters are changed.

In scope:

- A transaction model for moving graph state and KV state together.
- Manifest fields that bind graph hashes, artifact hashes, prompt hashes,
  tokenizer identity, token spans, and KV hashes.
- Source and target adapter responsibilities.
- Analyzer expectations for prompt, graph, and KV alignment.
- Acceptance criteria and failure cases for the first real MLX-to-vLLM
  graph-attached validation run.

Out of scope for the planning item:

- Changing the daemon wire protocol.
- Publishing the Agent Memory Graph schema as a stable public API.
- Migrating vector stores, raw credentials, or non-idempotent side effects.

Implemented follow-up:

- `adapters/agent_graph_span_metadata.py` builds and validates prompt-bound
  graph span metadata.
- The MLX live runtime attaches `agent_graph_span_metadata` for the same prompt
  token IDs used to prefill the source cache.
- The vLLM import worker validates that metadata before forwarding staged
  imports to its target hook and records the validation result in the processed
  marker.

## Current Inputs

The plan builds on existing repo surfaces:

- `docs/agent-memory-graph.md` defines the graph envelope, node and edge types,
  deterministic graph hashing, and KV span linkage.
- `examples/agent-memory-graph/local_agent.py` exports graph packages with graph,
  artifact, prompt, tokenizer, and simulated KV hashes.
- `permeant-cli sim-migrate --agent-graph-manifest <path>` embeds optional graph
  metadata in migration benchmark manifests.
- `adapters/analyze_real_runtime_fidelity.py` reports combined prompt, graph,
  and KV alignment when graph metadata is present.
- The live MLX and vLLM adapters already expose prompt tokenization evidence and
  real KV hash/slot-probe validation in the current E2E path.

## Transaction Model

Graph-attached KV migration should commit or roll back as one logical unit. A
target must not activate migrated KV state if the graph package fails
validation, and it must not mark graph state as resumed if the KV attachment
fails.

The first implementation should follow these stages:

1. `preflight`: source and target exchange capabilities, model identity,
   tokenizer identity, graph-package support, block geometry, and validation
   requirements.
2. `prepare_graph`: source records the graph package path, graph hash, artifact
   hashes, prompt byte hash, prompt token hash, tokenizer hash, KV span metadata,
   and expected KV hash.
3. `stream_kv`: source streams the signed/encrypted USXF tensor state as today.
4. `attach_graph`: source provides the graph package manifest or a
   content-addressed reference that the target can verify before activation.
5. `validate_alignment`: target validates graph hash, artifact hashes, prompt
   hashes, tokenizer identity, KV span coverage, KV block hashes, and runtime
   slot probes.
6. `commit`: target atomically binds the verified graph state to the migrated KV
   state and records a resume report.
7. `rollback`: any validation failure leaves no active migrated graph/KV session
   on the target.

The initial implementation can keep graph package transfer local or
manifest-referenced while the protocol is still research-grade. The acceptance
criteria require the target to verify the package contents before commit, not
necessarily to invent a new streaming format immediately.

## Required Invariants

Future protocol and adapter changes must preserve these invariants:

- `graph_hash` matches the canonical Agent Memory Graph payload.
- Every local artifact named by the graph package has a matching `sha256`.
- Prompt byte hash and prompt token hash match the source export.
- Tokenizer identity matches exactly, or the target explicitly reports a
  supported translation policy. The first real validation should require exact
  tokenizer match.
- Every graph `kv_span` maps to an existing graph node and to a migrated cache
  reference.
- KV span token ranges are non-overlapping or have an explicitly documented
  overlap policy.
- KV block hashes and runtime slot probes match the transferred tensor state.
- The target can explain which graph nodes map to the activated KV prefix.
- Tool calls with `side_effect` of `external_write` or `unknown` are never
  replayed during import unless a later policy milestone explicitly permits it.
- Secret values and raw cloud credentials are never copied through the graph
  package.
- Commit is all-or-nothing for graph state and KV state.

## Adapter Responsibilities

Source adapters must export:

- Model identity and runtime identity.
- Prompt text or a redacted prompt reference plus prompt byte hash.
- Prompt token IDs, prompt token hash, tokenizer hash, and tokenizer metadata.
- Agent Memory Graph package metadata and deterministic `graph_hash`.
- Artifact hashes and restore requirements.
- KV span to cache reference mappings.
- KV tensor/block hashes used by the existing migration path.

Target adapters must validate:

- Model compatibility and cache geometry.
- Tokenizer identity and prompt token view.
- Graph package hash and artifact hashes.
- KV span ranges against the target tokenizer view.
- KV block hashes and slot-level samples after cache write.
- Prefix-cache attachment or equivalent runtime binding.
- Resume report generation that names graph, prompt, tokenizer, and KV alignment
  status.

## Manifest Shape

The first graph-attached manifest should extend the existing optional
`agent_graph` section rather than introduce a second concept.

Required evidence for a graph-attached run:

```json
{
  "agent_graph": {
    "graph_hash": "sha256:...",
    "graph_path": "agent-memory-graph.json",
    "manifest_path": "agent-memory-manifest.json",
    "prompt_byte_hash": "sha256:...",
    "prompt_token_hash": "sha256:...",
    "tokenizer_hash": "sha256:...",
    "kv_hash": "sha256:...",
    "kv_spans": [
      {
        "node_id": "turn:user:1",
        "token_start": 0,
        "token_end": 256,
        "cache_ref": "kv:prefix:0",
        "block_hashes": ["sha256:..."]
      }
    ],
    "artifacts": [
      {
        "path": "artifacts/result.json",
        "sha256": "sha256:..."
      }
    ]
  }
}
```

The exact JSON field names may evolve with implementation, but the evidence
must remain present and machine-checkable.

## Analyzer Expectations

The analyzer should treat graph-attached migration as aligned only when all
three continuity layers pass:

- `alignment.prompt.status == "aligned"`
- `alignment.graph.status == "aligned"`
- `alignment.kv.status == "aligned"`

It should distinguish at least these failure classes:

- Missing graph package or missing graph metadata.
- Graph hash mismatch.
- Artifact hash mismatch.
- Prompt byte mismatch.
- Prompt token mismatch.
- Tokenizer mismatch.
- KV hash mismatch.
- KV span outside target context window.
- Slot-probe mismatch.
- Prefix-cache attachment failure.

Reports should preserve enough evidence to reproduce the failure without
including secrets, private prompts, or raw migration manifests in committed
fixtures.

## Acceptance Criteria

The graph-attached live KV migration runtime implementation is complete when:

- The source can export an Agent Memory Graph package and live KV cache for the
  same prompt/session.
- The migration manifest contains graph, artifact, prompt, tokenizer, KV hash,
  and KV span evidence for that run.
- The target validates graph package hashes before activation.
- The target validates prompt tokenization and tokenizer identity before
  activation.
- The target validates KV hashes or slot probes after cache write.
- The target binds the verified graph state to the activated KV prefix or records
  a clear unsupported state before rollback.
- The analyzer reports prompt, graph, and KV alignment as separate statuses.
- A real MLX-to-vLLM run preserves prompt reconstruction, prefix-cache
  attachment, slot-probe equality, and exact continuation fidelity for the
  current validation horizon.
- Failure injection covers graph hash tampering, artifact hash tampering, prompt
  token mismatch, tokenizer mismatch, KV hash mismatch, interrupted graph
  transfer, interrupted KV stream, and target rollback.
- Documentation explains limitations, compatibility assumptions, and side-effect
  safety boundaries.

## Implementation Sequence

Recommended next steps after this planning item:

1. Extend the simulated migration manifest with `kv_spans` and graph package
   attachment metadata behind the existing `--agent-graph-manifest` path.
2. Add analyzer checks for graph package availability, `kv_spans`, tokenizer
   hash, and failure classification.
3. Add CLI and adapter tests that reject malformed or inconsistent graph/KV
   metadata before commit.
4. Wire the live MLX source to emit graph package metadata for the same prompt
   used to prefill the KV cache.
5. Wire the vLLM target to validate token spans against its tokenizer view and
   report graph/KV binding status.
6. Add real-runtime failure injection and rollback checks once the happy path
   exists.

Items 1 and 2 are now prototyped through the existing Agent Memory Graph
manifest path: `kv_spans` are exported by the local harness, embedded by
`sim-migrate --agent-graph-manifest`, and reported by the analyzer as aligned,
partial, or diverged evidence. Live-runtime adapter production and target-side
validation remain the next implementation step.
