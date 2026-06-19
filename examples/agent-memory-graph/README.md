# Agent Memory Graph Local Harness

This example is the Phase 2 reference loop for graph-only Agent Memory Graph
migration. It intentionally avoids model/runtime dependencies so the export and
import behavior is fully inspectable.

The harness:

- runs a deterministic local agent session;
- writes one JSON artifact through a simulated `fs.write_file` tool call;
- exports `graph.json`, artifact blobs, and `manifest.json`;
- records graph hash, artifact hash, prompt byte hash, prompt token hash, and a
  simulated KV hash;
- imports the package and verifies every recorded hash;
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
    reports/
      result.json
```

This validates graph-only migration. Live KV-cache attachment remains a later
roadmap item.
