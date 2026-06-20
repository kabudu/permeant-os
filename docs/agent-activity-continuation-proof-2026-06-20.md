# Agent Activity Continuation Proof - 2026-06-20

This checkpoint adds an agent-level continuation proof above the existing
token/KV fidelity checks.

The previous AWS QATQ run proved that migrated KV state could be attached to the
target vLLM decode path and produce an exact 16-token continuation. That is a
runtime-output proof. It does not, by itself, prove that an agent resumed
pending work after import.

This proof validates the structured Agent Memory Graph resume path:

1. Export the complex 27-node agent package.
2. Import and verify graph hash, prompt hash, simulated KV hash, artifacts,
   vector memory, security policy, and side-effect replay policy.
3. Resume safe pending work after import.
4. Execute the retry-safe read-only quota check.
5. Execute the gated publish write only when explicit approval is supplied.
6. Append post-import tool result, artifact, event, and episodic memory nodes.
7. Emit a resume report with pre/post graph hashes and a proof hash.

## Command

```bash
python3 examples/agent-memory-graph/local_agent.py complex-demo \
  --output /tmp/permeant-agent-activity-proof-package

python3 examples/agent-memory-graph/local_agent.py resume \
  --input /tmp/permeant-agent-activity-proof-package \
  --workspace /tmp/permeant-agent-activity-proof-workspace \
  --approve-publish
```

## Result

| Field | Value |
| --- | --- |
| Status | `continued` |
| Activity continued | `true` |
| Pre-resume graph hash | `sha256:0aed9b05ca7e20ae43544f49191bf3f0c55ce21ec29beab20ac6a258f459a85b` |
| Post-resume graph hash | `sha256:f338313bf4876e92f3b31e07f9790e46629f1e8d01d8e93930a01e63c1eab7c8` |
| Prompt token hash | `sha256:139b4161d7096300f4e21e23cbddef915961707cb77999b00715cf9beadb76e6` |
| Simulated KV hash | `sha256:d55b7ca71c2419756572d407c6e065b9e6f89d23e5c598fd0caf7ca3baca7037` |
| Proof hash | `sha256:b066a1dba9ed250eb54e1344c8d0092d8ad2d90dfe68bbfc1a0c740d18b6969c` |

Executed post-import tool calls:

- `tool:call:read-aws-quota`: completed retry-safe read-only
  `aws.ec2.describe_instances` simulation.
- `tool:call:publish-release`: completed approved `fs.write_file` publish
  action.

Written post-import artifact:

- `reports/publish/announcement.md`
- hash: `sha256:374424754eb8fa627048cb5b6a4c4b755abde3114f6fd55c99212dfe57689269`
- size: 567 bytes

The resumed graph includes the new memory node
`memory:agent-activity-continued:post-import`, linked from the post-import
publish artifact. The graph hash changes after resume because new activity was
actually appended rather than merely revalidated.

## Safety Boundary

The resume harness does not replay completed side-effecting work. Completed
pre-migration writes remain `no_replay`. The pending read-only quota check may
retry automatically because it is marked `retry_safe`. The pending publish write
requires explicit approval; without `--approve-publish`, the harness records it
as blocked and does not write `reports/publish/announcement.md`.

This is an agent-activity proof for the deterministic Agent Memory Graph harness
over the same graph hash used in the AWS QATQ validation. It is not a private
reasoning-trace proof. It proves that imported structured agent state can resume
policy-governed tool work and produce new post-migration graph evidence.
