# Agent Memory Graph Local Harness

This example is the Phase 2 reference loop for graph-only Agent Memory Graph
migration. It intentionally avoids model/runtime dependencies so the export and
import behavior is fully inspectable.

The harness:

- runs deterministic local and complex agent sessions;
- writes one JSON artifact through a simulated `fs.write_file` tool call;
- exports `graph.json`, content-addressed artifact blobs, and `manifest.json`;
- records graph hash, artifact hash, prompt byte hash, prompt token hash, and a
  simulated KV hash;
- imports the package and verifies every recorded hash before restoring files;
- restores artifact files into a target workspace under a preserve-relative-path
  policy;
- supports export-time artifact redaction/exclusion rules that omit local blob
  bytes and force explicit target rebind before use;
- verifies and restores artifact blobs with streaming hash/copy helpers so large
  files do not need to be loaded into memory as one buffer;
- records and recomputes a side-effect audit for tool calls before import
  activation;
- packages a deterministic local vector-memory snapshot and verifies retrieval
  equivalence before import activation;
- reports hosted/external vector stores as explicit rebind-required state;
- verifies local security policy before activation, including graph-root
  attestation, provenance, target runtime, allowed tools, allowed artifact
  paths, raw secret rejection, and credential rebinding;
- reconstructs the prompt byte-for-byte;
- can generate a complex 27-node package with messages, artifacts, memories,
  retrieval evidence, credential rebinding, completed and pending tool policy,
  and one graph/KV span; and
- produces the same deterministic continuation after import.

Run:

```bash
python3 examples/agent-memory-graph/local_agent.py demo --output /tmp/permeant-agent-graph-demo
```

Generate and import the complex agent package used by the AWS real-runtime
proof:

```bash
python3 examples/agent-memory-graph/local_agent.py complex-demo \
  --output /tmp/permeant-complex-agent-graph
```

The exported package layout is:

```text
/tmp/permeant-agent-graph-demo/
  graph.json
  manifest.json
  artifacts/
    sha256/
      <prefix>/
        <digest>/
          result.json
  restored-workspace/
    reports/
      result.json
```

You can restore into an explicit workspace:

```bash
python3 examples/agent-memory-graph/local_agent.py import \
  --input /tmp/permeant-agent-graph-demo \
  --workspace /tmp/permeant-agent-graph-restored
```

The importer rejects absolute paths and `..` path traversal before writing
restored artifacts. Required artifacts fail import on missing blobs or hash
mismatch. Unresolved artifacts are rejected unless they use
`restore_policy: "external_rebind"` and `rebind_required: true`.

To omit artifact bytes from the exported package while preserving an explicit
rebind requirement:

```bash
python3 examples/agent-memory-graph/local_agent.py export \
  --output /tmp/permeant-agent-graph-redacted \
  --redact-artifact reports/result.json
```

`--exclude-artifact reports/result.json` follows the same safety boundary but
records the omission as an exclusion instead of a redaction.

The importer also audits every `tool_call` node before activation. Completed
side-effecting calls are marked `no_replay`, pending read-only calls marked
`retry_safe` may retry, and pending write/unknown calls must use an explicit
manual policy such as `ask_user`, `rebind`, or `compensate`. Unsafe automatic
replay policies fail import.

The importer validates vector memory continuity for the local snapshot mode:
embedding model, dimension, distance metric, record embedding hashes, and the
expected retrieval ranking must match after import. Vector `retrieval` nodes
must also match the snapshot ranking. Hosted vector stores can be represented
with `mode: "external_rebind"` and `rebind_required: true`; those imports report
`rebind_required` instead of pretending retrieval behavior is preserved.

The importer validates a security attestation before activation. Tampered
graph-root signatures, raw secret fields, untrusted target runtimes,
disallowed tools, disallowed artifact paths, and credential references that do
not require external rebind all fail import.

This validates graph-only migration locally. The complex package can also be
attached to the AWS real-runtime runner with `PERMEANT_AGENT_GRAPH_MANIFEST` to
validate graph/KV transaction binding against the live MLX-to-vLLM path.

To include the exported graph hashes in a local migration benchmark manifest,
pass the generated package manifest to `sim-migrate`:

```bash
./target/debug/permeant-cli sim-migrate \
  --target-addr 127.0.0.1:9099 \
  --seq-len 512 \
  --agent-graph-manifest /tmp/permeant-agent-graph-demo/manifest.json
```

The migration manifest will include an `agent_graph` section with graph, prompt,
artifact, tokenizer, simulated KV hashes, and graph-to-KV span metadata.

## Framework Adapter Conformance

`framework_adapters.py` contains dependency-free Phase 7 conformance mappings
for two independent framework-style runtimes:

- `langgraph_durable_state`
- `mcp_resource_session`

Print the adapter capability manifest:

```bash
python3 examples/agent-memory-graph/framework_adapters.py manifest
```

Export and verify a conformance package:

```bash
python3 examples/agent-memory-graph/framework_adapters.py export \
  langgraph_durable_state \
  /tmp/permeant-langgraph-conformance

python3 examples/agent-memory-graph/framework_adapters.py import \
  /tmp/permeant-langgraph-conformance
```

These mappings validate graph shape, adapter identity, graph hashes, actor
references, and edge references. They are not live LangGraph or MCP
integrations; they define the minimum graph contract future live adapters must
preserve.
