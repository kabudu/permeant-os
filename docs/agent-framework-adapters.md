# Agent Framework Adapter Conformance

Phase 7 adds the first Agent Memory Graph adapter conformance layer for
framework-style agent runtimes.

The executable reference lives at
`examples/agent-memory-graph/framework_adapters.py`. It deliberately avoids
third-party runtime dependencies so CI can validate the graph contract without
requiring LangGraph, MCP servers, browser sessions, or hosted services.

## Scope

The conformance layer provides:

- An adapter capability manifest.
- Two independent framework-style graph exports.
- A compatibility matrix derived from the manifest.
- Import verification for graph hashes, adapter/runtime identity, edge targets,
  and actor references.
- JSON Schema validation coverage in tests.

It does not yet connect to live framework APIs. Live adapter packages should use
these mappings as the minimum contract they must preserve when real runtime
state is exported.

## Current Adapters

| Adapter | Runtime family | Export modes | Import modes | Covered graph features |
| --- | --- | --- | --- | --- |
| `langgraph_durable_state` | `durable_state_graph` | `snapshot`, `checkpoint` | `resume_from_checkpoint`, `rebind_store` | messages, tasks, checkpoints, semantic memories, retrievals, trace spans |
| `mcp_resource_session` | `tool_resource_session` | `snapshot`, `capability_rebind` | `resume_read_only_tools`, `rebind_capabilities` | messages, tool calls, tool results, credential refs, artifacts, trace spans |

The two adapters are intentionally different. The LangGraph-style adapter
models durable thread state and long-term memory stores. The MCP-style adapter
models resource/tool calls, returned resource links, and rebindable
capabilities.

## Commands

Print the adapter capability manifest:

```bash
python3 examples/agent-memory-graph/framework_adapters.py manifest
```

Print the compatibility matrix:

```bash
python3 examples/agent-memory-graph/framework_adapters.py matrix
```

Export one conformance package:

```bash
python3 examples/agent-memory-graph/framework_adapters.py export \
  langgraph_durable_state \
  /tmp/permeant-langgraph-conformance
```

Verify an exported package:

```bash
python3 examples/agent-memory-graph/framework_adapters.py import \
  /tmp/permeant-langgraph-conformance
```

## Verification Rules

The conformance importer rejects:

- Graph hash mismatch.
- Adapter manifests that do not include the graph adapter ID.
- Runtime mismatch between graph and adapter manifest.
- Nodes whose `actor_id` does not appear in participants.
- Edges whose source or target node does not exist.

The test suite also validates every adapter graph against
`docs/schemas/agent-memory-graph-v0.schema.json`.

## Limitations

These are reference mappings, not live integrations. Real LangGraph, MCP,
OpenAI Agents SDK, browser, or other framework adapters still need runtime API
wiring, credential rebinding, live session storage, and framework-specific
failure handling. The conformance layer defines the minimum portable graph
shape those future adapters must satisfy.
