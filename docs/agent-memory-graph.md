# Agent Memory Graph v0

Status: prototype schema for the v0.2 Agent Graph Prototype milestone.

The Agent Memory Graph is the structured continuity layer above USXF KV-cache
migration. It describes the agent state that must survive relocation:
conversation turns, tool calls, tool results, artifacts, durable memories,
pending work, provenance, credential references, and links to migrated KV spans.

The canonical machine-readable schema lives at
`docs/schemas/agent-memory-graph-v0.schema.json`.

## Research Calibration

This v0 schema was reviewed against the main patterns used by current agent
memory systems:

- Hierarchical context managers such as MemGPT/Letta distinguish active context,
  recall storage, archival storage, and self-directed memory edits.
- LangGraph-style systems separate thread-scoped short-term state from
  namespace-scoped long-term stores, and commonly classify memory as semantic,
  episodic, or procedural.
- Graph memory systems such as Zep/Graphiti and Mem0 graph memory emphasize
  temporal facts, relation extraction, belief revision, and cross-session
  retrieval provenance.
- API-backed session systems such as OpenAI Agents SDK sessions and Responses
  conversation state preserve ordered items, tool calls, tool outputs,
  compaction, interrupted runs, and trace spans.
- MCP-style tool/resource systems require explicit capability metadata, resource
  links, structured tool results, human approval, and trust boundaries.
- Mnemara-style local-first stores add useful operational detail: explicit
  memory quality and historical lifecycle states, trust levels, episodic
  continuity, salience and boundary cues, conflict review, explainable recall
  planner traces, score breakdowns, time-travel/historical recall modes,
  lineage-preserving compaction, changefeed-friendly mutation history, and
  portable snapshot/export packages.

The schema therefore models both raw continuity records and higher-level memory
objects. It is intentionally an exchange schema: it can represent the durable
state needed for migration without prescribing a single retrieval algorithm,
database layout, or agent control loop.

## Goals

- Represent a simple chat, tool, and artifact session as a portable graph.
- Hash the graph deterministically across runtimes.
- Link graph nodes to token spans and KV cache references.
- Make unsafe side effects visible before import or resume.
- Preserve memory tier, retrieval, compaction, checkpoint, and trace provenance.
- Represent temporal validity and belief revision without forcing one memory
  backend.
- Leave extension room without weakening validation of the core fields.

## Envelope

```json
{
  "graph_id": "graph:example:20260619",
  "graph_version": "0.1",
  "created_at": "2026-06-19T00:00:00Z",
  "agent": {
    "id": "agent:example",
    "runtime": "local-loop",
    "model": "Qwen/Qwen2.5-0.5B-Instruct"
  },
  "participants": [],
  "nodes": [],
  "edges": [],
  "kv_spans": [],
  "graph_hash": "sha256:..."
}
```

Required top-level fields:

- `graph_id`: stable identifier for this exported graph snapshot.
- `graph_version`: schema version. The initial value is `0.1`.
- `created_at`: RFC 3339 UTC export timestamp.
- `agent`: source agent identity and runtime metadata.
- `nodes`: ordered list of state nodes.
- `edges`: ordered list of graph relationships.
- `kv_spans`: token span to cache-reference mappings.
- `graph_hash`: deterministic hash of the graph payload.

Optional top-level fields:

- `participants`: users, agents, tools, services, and human approvers that
  appear in the graph.
- `source_graph_id`: previous graph snapshot when this export is derived from an
  earlier migration.
- `lineage`: ordered migration/export history for multi-hop provenance.
- `policies`: graph-level redaction, retention, replay, and import policy.

`extensions` is optional at the top level and on nodes. Extension keys must be
namespaced, for example `com.example.trace_id`.

## Node Types

All nodes include:

- `id`: stable graph-local identifier.
- `type`: one of the node types below.
- `created_at`: RFC 3339 UTC timestamp.
- `content_hash`: `sha256:` hash of the node payload.
- `provenance`: source runtime and capture metadata.
- `actor_id`: optional participant that created or owns the node.
- `memory_scope`: optional scope such as `thread`, `user`, `org`, `agent`, or
  `global`.
- `memory_tier`: optional storage tier such as `active_context`, `working`,
  `recall`, `archival`, `profile`, `vector_index`, or `external`.
- `sensitivity`: optional classification for import policy and redaction.
- `quality_state`: optional memory quality marker such as `active`, `verified`,
  `pinned`, `archived`, `suppressed`, or `deleted`.
- `historical_state`: optional lifecycle marker such as `current`,
  `historical`, or `superseded`.
- `trust_level`: optional trust marker such as `unknown`, `untrusted`,
  `derived`, `operator_reviewed`, or `verified`.
- `valid_at`, `invalidated_at`, and `confidence`: optional temporal/belief
  metadata for facts and memories.

Core node types:

| Type | Purpose |
| --- | --- |
| `event` | Runtime, user, scheduler, approval, or system event. |
| `message` | System, user, assistant, or tool-visible conversation content. |
| `tool_call` | A tool invocation, including side-effect and retry policy. |
| `tool_result` | Result of a tool invocation. |
| `plan` | Current or historical agent plan/checklist state. |
| `task` | A resumable unit of work with lifecycle state. |
| `artifact` | File, blob, or external artifact reference. |
| `memory` | Durable semantic memory or retrieval chunk. |
| `retrieval` | A retrieval query/result set used to build model context. |
| `summary` | Compacted or lossy summary of prior nodes. |
| `checkpoint` | Resume point for session, graph, or runtime state. |
| `trace_span` | Observability span for model, tool, or orchestration work. |
| `handoff` | Transfer between agents, runtimes, or humans. |
| `credential_ref` | Rebindable credential or capability reference, never a secret value. |
| `kv_span` | Graph node that anchors a token span to a KV cache reference. |

### Event Nodes

Event nodes represent non-message triggers: scheduler ticks, context-window
warnings, user approvals, cancellation requests, external webhooks, or runtime
interruptions. They require `event_kind`.

### Message Nodes

Message nodes require `role` and either inline `content` or an external
`content_ref`.

Allowed roles are `system`, `user`, `assistant`, and `tool`.

### Tool Call Nodes

Tool calls capture enough state to avoid accidental replay:

- `name`: tool name.
- `provider`: tool server or runtime namespace when known.
- `call_id`: runtime call identifier.
- `arguments_hash`: hash of canonicalized arguments.
- `input_schema_hash`: hash of the declared input schema when available.
- `idempotency_key`: stable key when the tool supports safe retry.
- `side_effect`: `none`, `read_only`, `external_write`, or `unknown`.
- `status`: `not_started`, `in_progress`, `completed`, `failed`, `cancelled`, or
  `needs_user`.
- `resume_policy`: `retry_safe`, `never_retry`, `ask_user`, `rebind`, or
  `compensate`.
- `approval_state`: `not_required`, `requested`, `approved`, `denied`, or
  `expired`.
- `consent_ref`: optional reference to a human approval or policy decision.
- `external_resource_ids`: optional identifiers created or touched by the call.

Importers must not automatically replay a tool call with `side_effect` of
`external_write` or `unknown` unless `resume_policy` explicitly permits it.
The local reference harness now records a `side_effect_audit` during export and
recomputes it during import before activation. Completed side-effecting tool
calls are preserved with a `no_replay` action. Pending `read_only` or `none`
calls marked `retry_safe` may retry. Pending `external_write` or `unknown` calls
must use an explicit manual policy such as `ask_user`, `rebind`, or
`compensate`; automatic retry of those calls fails import. Pending calls with
denied or expired approval also fail import.

### Tool Result Nodes

Tool results capture both unstructured and structured outputs:

- `result_hash`: hash of the canonical result payload.
- `output_schema_hash`: hash of the structured output schema when available.
- `is_error`: whether the tool completed with a tool-level error.
- `resource_refs`: optional resource URIs returned by the tool.

### Artifact Nodes

Artifact nodes describe either content-addressed local blobs or external
references:

- `artifact_kind`: `file`, `directory`, `blob`, or `external`.
- `path`: source-relative path when applicable.
- `uri`: stable URI for local or external resources.
- `sha256`: required for local content.
- `size_bytes`: content size when known.
- `media_type`: optional MIME type.
- `root_ref`: optional workspace/root boundary that authorized access.
- `restore_policy`: `required`, `optional`, `quarantine_on_mismatch`, or
  `external_rebind`.

The local reference harness packages file artifacts in a content-addressed blob
store under `artifacts/sha256/<prefix>/<digest>/`. Import first verifies the
manifest hash, graph hash, artifact hash, and artifact size, then restores each
required artifact into a target workspace using a preserve-relative-path policy.
Artifact verification and restore use streaming hash/copy helpers so large blobs
do not need to be loaded as one in-memory buffer. Absolute paths and `..`
traversal are rejected before any target file is written. Missing or mismatched
required artifacts fail import. Redacted or excluded artifact bytes may be
omitted from a package only when the manifest marks the artifact with
`restore_policy: "external_rebind"` and `rebind_required: true`; unresolved
artifact references without that explicit rebind policy fail import.

### Memory Nodes

Memory nodes represent raw records, facts, profiles, summaries, retrieval
chunks, and external bindings:

- `memory_kind`: `raw_event`, `semantic`, `episodic`, `procedural`, `profile`,
  `retrieval_chunk`, `entity`, `relationship`, `summary`, `vector_binding`, or
  `external_binding`.
- `text_hash`: hash of textual memory content when exported.
- `subject`, `predicate`, and `object`: optional fact/relation fields.
- `namespace` and `key`: optional store location for namespace-based memory.
- `embedding_model`: embedding model identity when vectors are involved.
- `embedding_dim`, `embedding_hash`, and `distance_metric`: vector metadata
  without requiring raw vector export.
- `vector_store_ref`: external vector store binding when not snapshotted.
- `episode`: optional episodic continuity metadata: episode ID, continuity
  state, actor participation, recurrence key, timeline bounds, boundary labels,
  causal/previous/next/related record references, salience, and affective
  annotations.
- `conflict`: optional review metadata for contradictions or drift: review
  state, conflicting node IDs, drift score, resolver, resolution kind, and note.
- `lineage_links`: optional links to source, superseded, compacted, archived, or
  imported records.

### Retrieval Nodes

Retrieval nodes preserve why a memory or artifact entered context:

- `query_hash`: hash of the query or retrieval prompt.
- `retrieval_kind`: `keyword`, `vector`, `graph`, `hybrid`, `temporal`, or
  `manual`.
- `planner_profile`: retrieval planning profile, such as `fast_path` or
  `continuity_aware`.
- `policy_profile`: recall policy profile, such as `general`, `support`,
  `research`, `assistant`, or `autonomous_agent`.
- `selected_channels`, `candidate_sources`, `planner_stages`, and
  `graph_expansion_max_hops`: explainable retrieval planning metadata.
- `historical_mode` and `time_travel_at`: current, historical, mixed, lineage,
  or time-travel recall view.
- `results`: ordered result references with scores, ranks, and source node IDs.
- `score_breakdown` on each result: lexical, semantic, temporal, episodic,
  provenance, or adapter-defined score components.
- `selection_policy`: policy used to choose context items.

### Summary And Checkpoint Nodes

Summary nodes represent compaction. They must record whether the summary is
lossy, the source node IDs, and the summarizer identity when available.

Checkpoint nodes represent resumable runtime/session state, including
`checkpoint_kind`, `state_hash`, and optional `resume_ref`. Snapshot and
portable-package checkpoint kinds are available for local-first stores that can
round-trip memory packages across backends.

### Trace And Handoff Nodes

Trace spans preserve observability context for model calls, tool calls, and
orchestration decisions. Handoff nodes record transfers between agents, humans,
or runtimes, including `from_actor_id`, `to_actor_id`, and `handoff_reason`.

### Credential Reference Nodes

Credential references must never contain secret material. They describe how a
target runtime can rebind a capability:

- `capability`: provider-specific capability name.
- `binding`: target rebinding hint.
- `required`: whether import must fail if the credential cannot be rebound.

## Edge Types

Edges are directed and use graph-local node IDs:

| Type | Meaning |
| --- | --- |
| `caused` | Source node caused or requested target node. |
| `derives_from` | Target node was derived from source node. |
| `references` | Source node references target node. |
| `produced` | Source node produced target artifact/result. |
| `consumed` | Source node consumed target artifact/memory/capability. |
| `supersedes` | Source node replaces target node. |
| `resumes` | Source node resumes target pending state. |
| `retrieved` | Source retrieval node selected target node. |
| `summarizes` | Source summary node compacts target node. |
| `checkpointed` | Source checkpoint captured target node/state. |
| `handoff_to` | Source handoff delegates or transfers to target. |
| `approves` | Source approval event authorizes target action. |
| `invalidates` | Source node makes target node stale or false. |

Importers must reject edges whose `from` or `to` values do not match an existing
node ID.

## KV Spans

`kv_spans` link graph continuity to token/cache continuity:

```json
{
  "node_id": "turn:user:1",
  "token_start": 128,
  "token_end": 256,
  "cache_ref": "kv:prefix:0",
  "tokenizer_hash": "sha256:...",
  "block_hashes": ["sha256:..."]
}
```

Rules:

- `token_start` is inclusive.
- `token_end` is exclusive.
- `token_end` must be greater than `token_start`.
- `node_id` must refer to an existing node.
- `cache_ref` must be stable within the migration manifest.
- `tokenizer_hash` is required when the span is intended for cross-runtime
  import.

## Security And Policy

The graph is allowed to describe sensitive state, but it must not silently copy
capabilities that belong to a user, organization, or host:

- Secret values must be represented as `credential_ref` nodes or redacted
  artifacts, not inline strings.
- Tool calls that can mutate external systems require explicit
  `side_effect`, `approval_state`, and `resume_policy`.
- Resource and artifact nodes should include `root_ref` or another access
  boundary when derived from a filesystem or external store.
- Sensitive nodes should set `sensitivity`, `retention`, and `redaction_state`
  so importers can reject, quarantine, or rebind state before activation.

## Deterministic Hashing

`graph_hash` is computed over the graph envelope after removing `graph_hash` and
serializing JSON canonically:

1. UTF-8 JSON.
2. Object keys sorted lexicographically at every level.
3. No insignificant whitespace.
4. Arrays preserved in declared order.
5. Hash algorithm `sha256`.

The resulting string is encoded as `sha256:<hex>`.

Each `content_hash` uses the same canonicalization rule over the stable payload
for that node type. Runtime-specific debug metadata belongs in `extensions` and
must be excluded from `content_hash` unless the extension declares otherwise.

## Compatibility

Readers must accept graphs with the same major version and a lower or equal
minor version. Readers may preserve unknown namespaced extension fields, but
must reject unknown core node or edge types.

Writers must set `graph_version` to the lowest schema version that can represent
the exported graph.

## Minimal Example

See `tests/fixtures/agent_memory_graph_v0.json` for a complete fixture covering
message, tool call, tool result, artifact, plan, memory, credential reference,
and KV-span representation.

## Implementation Checklist

- [x] Review current agent memory systems and fold their schema implications into
  v0.
- [x] Consider Mnemara's local-first, explainable retrieval and lifecycle model.
- [x] Define the v0 graph envelope and compatibility policy.
- [x] Define core node and edge types.
- [x] Define deterministic graph and node hashing rules.
- [x] Define KV-span linkage to cache references.
- [x] Add machine-readable JSON schema.
- [x] Add a validation fixture and schema test.
- [x] Build the minimal local export/import harness.
- [x] Add graph hash fields to migration manifests.
- [x] Extend the analyzer to report prompt, graph, and KV alignment together.
- [x] Define graph-attached live KV migration planning notes and acceptance
  criteria.
- [x] Prototype graph-attached live KV migration manifest extensions and analyzer
  checks.
- [ ] Implement live-runtime graph-attached span production and target
  validation.
