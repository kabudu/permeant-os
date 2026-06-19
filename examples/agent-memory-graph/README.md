# Agent Memory Graph Local Harness

This example is the Phase 2 reference loop for graph-only Agent Memory Graph
migration. It intentionally avoids model/runtime dependencies so the export and
import behavior is fully inspectable.

The harness:

- runs a deterministic local agent session;
- writes one JSON artifact through a simulated `fs.write_file` tool call;
- exports `graph.json`, content-addressed artifact blobs, and `manifest.json`;
- records graph hash, artifact hash, prompt byte hash, prompt token hash, and a
  simulated KV hash;
- imports the package and verifies every recorded hash before restoring files;
- restores artifact files into a target workspace under a preserve-relative-path
  policy;
- reconstructs the prompt byte-for-byte; and
- produces the same deterministic continuation after import.

Run:

```bash
python3 examples/agent-memory-graph/local_agent.py demo --output /tmp/permeant-agent-graph-demo
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
mismatch; future external artifacts can use rebind or quarantine policies.

This validates graph-only migration. Live KV-cache attachment remains a later
roadmap item.

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
