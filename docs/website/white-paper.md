# PermeantOS White Paper

## Live migration for AI agent state

PermeantOS is an open-source research-preview system for live AI agent migration. It introduces a state-fluid hypervisor and the Unified State Exchange Format (USXF), a runtime-neutral format for moving active AI state across heterogeneous model runtimes.

Today, PermeantOS focuses on live KV-cache migration: moving the active attention cache of a long-running model from one host to another so an agent can resume without expensive re-prefill. The longer-term roadmap extends this into full Agent Memory Graph migration, including conversation turns, tool calls, artifacts, retrieval memory, provenance, and pending work. The first graph milestone, the v0 schema and specification, is now defined.

## Why this matters

Long-running AI agents accumulate context. That context is expensive to reconstruct. If an agent has to move from a laptop to a cloud GPU, from one cloud host to another, or away from a node scheduled for shutdown, the usual approach is to replay or re-prefill the prompt. For long contexts, that can be slow and expensive.

PermeantOS treats agent state as portable infrastructure. Instead of binding state to one machine or runtime, it provides a migration layer that can extract, transfer, verify, and attach live KV cache state on a target runtime.

## What has been demonstrated

PermeantOS has demonstrated a real cross-runtime migration from a local Apple Silicon MLX source runtime to an AWS NVIDIA vLLM target runtime.

Validated run:

| Field | Value |
| --- | --- |
| Source | MLX on Apple Silicon |
| Target | AWS `g4dn.xlarge`, vLLM `0.23.0` |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Prefix length | 2016 tokens |
| Layers | 24 |
| Hash validation | passed |
| Slot-probe max key diff | `0.0` |
| Slot-probe max value diff | `0.0` |
| Prefix-cache seeded blocks | 16 |
| Decode fidelity | exact source/post-migration match for 16 generated tokens |

The run proves the core path: live MLX extraction, secure transport, target-side vLLM KV allocation, direct KV write, prefix-cache attachment, and post-migration continuation fidelity.

## Architecture

PermeantOS migration has eight main stages:

1. Capability exchange between source and target.
2. Warm-start decision comparing migration cost with re-prefill cost.
3. Source runtime KV extraction.
4. Layout normalization into USXF.
5. Encrypted and signed payload transfer.
6. CRC-checked streaming to the target daemon.
7. Target KV allocation, reshape, write, and prefix-cache attachment.
8. Two-phase commit and validation.

USXF is the exchange layer. It records model identity, attention structure, sequence length, tensor dtype, transfer quantization, block hashes, checksums, and signatures.

## The key finding

An earlier validation run appeared to show a source/target continuation mismatch. The root cause was not a KV migration defect. The target context window was exhausted before the full validation continuation could be generated. Reducing the migrated prefix to leave enough target context room produced exact 16-token source/post-migration fidelity.

This matters because migration fidelity tests must account for tokenizer and runtime-specific context-window behavior. PermeantOS now records enough fidelity metadata to distinguish true migration defects from context exhaustion.

## Roadmap: Agent Memory Graph migration

KV cache migration is the first layer. Full agent migration requires more.

The Agent Memory Graph v0 schema now defines:

- conversation turns;
- tool calls and tool results;
- files and generated artifacts;
- retrieval memories and vector-store bindings;
- pending actions and idempotency policy;
- provenance and signatures;
- token-span mappings from graph nodes to KV cache ranges.

The next implementation step is a minimal local export/import harness, followed by graph hash fields in migration manifests and graph-attached KV migration. The goal is to migrate not just model activations, but agent continuity.

## Status

PermeantOS is a research preview. It is substantial enough to release and reproduce, but not production-ready.

Current strengths:

- Real cross-runtime proof point.
- Rust core protocol and daemon.
- MLX and vLLM live runtime adapters.
- Agent Memory Graph v0 schema and specification.
- Minimal local Agent Memory Graph export/import harness.
- Optional Agent Memory Graph hash metadata in migration manifests.
- Repeatable AWS E2E runner with cleanup verification.
- Paper and roadmap.

Current limitations:

- Fidelity has been validated for one model family and a short continuation horizon.
- vLLM integration relies on internal runtime behavior that may change.
- Python adapters are needed for Python-native ML runtimes.
- Agent Memory Graph export/import and graph-attached KV migration are planned but not yet implemented.

## Learn more

- Paper source: `docs/usxf-arxiv-paper.md`
- arXiv bundle: `paper/arxiv/`
- Roadmap: `ROADMAP.md`
- Agent Memory Graph schema: `docs/agent-memory-graph.md`
- Local graph harness: `examples/agent-memory-graph/`
- AWS E2E runbook: `docs/aws-real-runtime-e2e-runner.md`
