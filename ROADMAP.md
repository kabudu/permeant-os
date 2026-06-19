# PermeantOS Roadmap

PermeantOS currently proves live KV-cache migration across real heterogeneous runtimes: a local Apple Silicon MLX source can migrate a Qwen2.5 KV cache to an AWS NVIDIA vLLM target, seed the target prefix cache, and produce exact 16-token continuation fidelity for the validated run.

This roadmap describes the next major expansion: full agent memory graph migration. The goal is to migrate not only KV cache tensors, but the structured continuity state of an agent: conversation state, tool calls, artifacts, retrieval memory, pending work, provenance, and the KV spans that make resumed decoding fast.

## Current baseline

Implemented and validated:

- Rust hypervisor daemon and migration client.
- Capability exchange and two-phase commit flow.
- Encrypted and signed transfer envelope.
- CRC-checked streaming payload frames.
- USXF-style tensor metadata and manifests.
- MLX source adapter for live KV extraction.
- vLLM target adapter for live KV allocation, direct slot writes, prefix-cache seeding, and continuation validation.
- Repeatable AWS real-runtime E2E runner with cleanup verification.
- Manifest and fidelity analysis tooling.
- Exact MLX-to-vLLM 16-token decode fidelity for `Qwen/Qwen2.5-0.5B-Instruct` at a 2016-token prefix.

Known limitations:

- Fidelity has been validated for one model family and a short continuation horizon.
- Fresh cloud hosts are slow because vLLM, Torch, CUDA packages, model weights, and kernels are cold-installed or warmed during each run.
- Python adapters are still required for Python-native runtimes such as MLX and vLLM.
- KV cache migration is not yet packaged as a stable public runtime API.
- Full agent state, tools, files, vector stores, and pending side effects are not yet migrated as a graph.

## North star

A user should be able to pause or relocate an agent from one host/runtime to another and resume with equivalent continuity:

- Same conversation and instruction state.
- Same relevant long-context KV prefix when compatible.
- Same tool-call history and artifact references.
- Same durable memories and retrieval context.
- Same pending plan where safe to resume.
- Clear provenance for every migrated state component.
- No accidental replay of non-idempotent side effects.

## Phase 1: Agent Memory Graph v0 schema

Define a graph layer above KV cache.

Deliverables:

- `docs/agent-memory-graph.md` specification.
- JSON schema for graph export/import.
- Node types for messages, tool calls, tool results, plans, artifacts, memories, credentials references, and KV spans.
- Edge types for causal order, derives-from, references, produced, consumed, supersedes, and resumes.
- Stable IDs for graph nodes and edges.
- Graph-level checksum and per-node hashes.
- Version field, compatibility policy, and extension namespace rules.

Proposed minimal shape:

```json
{
  "graph_version": "0.1",
  "agent": {
    "id": "agent:example",
    "runtime": "local-loop",
    "model": "Qwen/Qwen2.5-0.5B-Instruct"
  },
  "nodes": [
    {"id": "turn:1", "type": "message", "role": "user", "content_hash": "sha256:..."},
    {"id": "tool:1", "type": "tool_call", "name": "aws.ec2.run_instances", "idempotency_key": "..."},
    {"id": "artifact:1", "type": "file", "path": "reports/result.json", "sha256": "..."}
  ],
  "edges": [
    {"from": "turn:1", "to": "tool:1", "type": "caused"},
    {"from": "tool:1", "to": "artifact:1", "type": "produced"}
  ],
  "kv_spans": [
    {"node_id": "turn:1", "token_start": 128, "token_end": 256, "cache_ref": "kv:prefix:0"}
  ]
}
```

Exit criteria:

- A graph can represent a simple chat/tool/artifact session.
- The graph can be hashed deterministically.
- A migrated KV prefix can be linked to graph token spans.

## Phase 2: Minimal local agent export/import harness

Create a small reference agent loop that is intentionally simple and fully inspectable.

Deliverables:

- Example local agent runtime under `examples/agent-memory-graph/`.
- Export command that emits graph JSON plus artifact blobs.
- Import command that reconstructs the agent state.
- Deterministic prompt reconstruction from graph nodes.
- Manifest that records graph hash, artifact hashes, prompt token hash, and KV hash.

Validation:

- Export an agent after several turns and one tool call.
- Import on the same machine.
- Reconstruct the prompt byte-for-byte or token-for-token.
- Continue the agent with the same next response under deterministic decoding.

Exit criteria:

- Graph-only migration works without live KV migration.
- Prompt reconstruction is deterministic.
- Artifacts referenced by the graph are present and hash-verified after import.

## Phase 3: KV-attached graph migration

Attach existing PermeantOS KV migration to the graph layer.

Deliverables:

- Graph nodes include token spans and KV cache references.
- Migration manifest includes both tensor state and graph state.
- Import path verifies that graph token spans match the target tokenizer view.
- Analyzer reports graph/KV alignment status.

Validation:

- Export graph and KV cache from the MLX source.
- Migrate both to vLLM target.
- Verify prompt reconstruction, KV hash validation, slot-probe equality, prefix-cache attachment, and continuation fidelity.

Exit criteria:

- A resumed target can explain which graph nodes map to the migrated KV prefix.
- Decode fidelity remains exact for the validation horizon.
- Analyzer can distinguish graph mismatch, tokenizer mismatch, KV mismatch, and context-window exhaustion.

## Phase 4: Artifact and filesystem migration

Move generated files and structured artifacts as first-class graph objects.

Deliverables:

- Content-addressed artifact store.
- Path mapping policy for target workspaces.
- Redaction/exclusion rules.
- Large-file streaming support.
- Artifact restore report.

Validation:

- Agent creates files, references them in messages/tool outputs, migrates, and resumes with the same files available.
- Hash mismatch causes import failure or quarantine.

Exit criteria:

- File artifacts are reproducibly restored.
- Graph references never point at missing files unless explicitly marked external.

## Phase 5: Tool-call replay and side-effect safety

Prevent duplicated external side effects during migration and resume.

Deliverables:

- Tool-call node schema with idempotency keys.
- Pending action states: `not_started`, `in_progress`, `completed`, `failed`, `cancelled`, `needs_user`.
- Resume policies: `retry_safe`, `never_retry`, `ask_user`, `rebind`, `compensate`.
- Tool result provenance and external resource IDs.
- Side-effect audit log.

Validation:

- A completed cloud provisioning tool call is not repeated after import.
- A pending safe read-only tool call may retry.
- A non-idempotent write action requires explicit policy before resume.

Exit criteria:

- Migration can preserve pending work without duplicating destructive or billable actions.
- Analyzer reports unsafe pending actions before commit.

## Phase 6: Vector and retrieval memory support

Support external and embedded memory stores.

Deliverables:

- Memory node type for semantic memories and retrieval chunks.
- Vector store binding metadata.
- Snapshot mode for small/local vector stores.
- Rebind mode for hosted vector stores.
- Embedding model identity and index compatibility checks.

Validation:

- Query results before and after migration are equivalent for a test corpus.
- Missing external vector store credentials produce a clear rebind-required state.

Exit criteria:

- Agent retrieval behavior is preserved or safely marked degraded.

## Phase 7: Runtime adapters for real agent frameworks

Add adapters for common agent systems while keeping the core protocol framework-neutral.

Candidate adapters:

- Minimal local reference loop.
- LangGraph-style durable state.
- OpenAI Agents SDK-style traces/state when suitable APIs are available.
- MCP-backed tool/resource sessions.
- Browser/session state where safe to represent as rebindable capability references.

Deliverables:

- Adapter capability manifest.
- Export/import conformance tests.
- Compatibility matrix.

Exit criteria:

- At least two independent agent runtimes can export/import the Agent Memory Graph v0 schema.

## Phase 8: Security, provenance, and policy

Harden graph migration for real users and shared infrastructure.

Deliverables:

- Per-node signatures or signed graph roots.
- Redaction policies for secrets and credentials.
- Capability rebinding instead of raw credential copying.
- Provenance chain across multi-hop migrations.
- Policy hooks for allowed target runtimes, allowed tools, and allowed artifact paths.
- Threat model document.

Validation:

- Secret values are excluded or encrypted according to policy.
- Tampered graph nodes are detected.
- Target refuses incompatible or untrusted graph imports.

Exit criteria:

- A graph migration can be audited after the fact.
- Sensitive external capabilities are not silently copied to new machines.

## Phase 9: Performance and reliability hardening

Make repeated validation boring and affordable.

Deliverables:

- Prewarmed AWS AMI or container image with Rust toolchain, vLLM, CUDA stack, and model weights.
- Longer-horizon decode-fidelity benchmark suite.
- Larger context runs beyond 2k tokens.
- Transfer quantization comparison for real-runtime fidelity.
- Failure-injection tests for interrupted graph and KV migration.
- Structured benchmark output suitable for paper updates.

Exit criteria:

- Real-runtime E2E runs complete without manual cloud setup.
- Cleanup is verified automatically.
- CI or scheduled external validation can run against disposable infrastructure.

## Phase 10: Public API and release packaging

Turn research prototype surfaces into documented integration points.

Deliverables:

- Stable USXF/Agent Memory Graph versioning policy.
- Rust crates API documentation.
- Python adapter SDK documentation.
- Example applications.
- Release checklist.
- Compatibility guarantees for manifests and graph schemas.

Exit criteria:

- External contributors can build an adapter without reading PermeantOS internals.
- Users can run a minimal local demo in minutes.
- Cloud E2E validation has a repeatable recipe and known cost envelope.

## Release milestones

### v0.1 Research Preview

Scope:

- Current KV migration system.
- Real MLX-to-vLLM fidelity proof.
- Paper draft.
- Open-source project hygiene.
- Clear limitations and roadmap.

Quality bar:

- Builds locally from documented steps.
- Reproducible local mock migration.
- Documented AWS real-runtime validation path.
- License, contributing, security, and code of conduct present.

### v0.2 Agent Graph Prototype

Scope:

- Agent Memory Graph v0 schema.
- Minimal local graph export/import harness.
- Artifact migration.
- Graph manifest hashing.

### v0.3 KV-Attached Graph Migration

Scope:

- Graph plus live KV migration in one transaction.
- Token-span alignment verification.
- Real MLX-to-vLLM graph-attached E2E run.

### v0.4 Framework Adapters

Scope:

- At least two real agent-runtime adapters.
- Tool replay policies.
- Vector memory rebind/snapshot support.

### v1.0 Stable Research System

Scope:

- Stable USXF and Agent Memory Graph schemas.
- Security policy and provenance model.
- Reproducible multi-model benchmark suite.
- Documented extension API.

## Open research questions

- How long must continuation fidelity be validated before a migration is considered behaviorally equivalent?
- How should graph nodes map to tokenizer-specific spans across runtimes with subtly different prompt formatting?
- Which external capabilities should be migratable, rebindable, or explicitly non-migratable?
- How should non-idempotent in-flight tool calls be represented in a way that is both safe and useful?
- Can prefix-cache migration be generalized across vLLM versions without relying on unstable internals?
- What is the right boundary between PermeantOS and existing distributed cache systems such as LMCache or Mooncake?

## Immediate next steps

- [x] Add `docs/agent-memory-graph.md` with the v0 schema.
- [ ] Build a minimal local graph export/import example.
- [ ] Add graph hash fields to migration manifests.
- [ ] Extend the analyzer to report prompt, graph, and KV alignment together.
- [ ] Prepare a prewarmed AWS image or container to reduce E2E cycle time.
