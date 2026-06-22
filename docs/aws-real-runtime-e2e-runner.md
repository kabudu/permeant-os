# AWS real-runtime E2E runner

This runbook standardizes the MLX laptop to AWS `vLLM` real-runtime test path. The goal is a boring, repeatable process: provision, setup, start target services, run migration, collect artifacts, analyze fidelity, and clean up.

## Script

Use:

```bash
scripts/aws-real-runtime-e2e.sh preflight
scripts/aws-real-runtime-e2e.sh run
```

The runner creates a per-run state directory under:

```text
.permeant-e2e/aws/<run-id>/
```

The state directory contains:

- `state.json`: AWS IDs, connection metadata, model, source URL, artifact paths
- `preflight-report.json`: non-provisioning readiness report when `preflight`
  is run
- `migration.log`: local migration output
- `vllm-runtime-probe.json`: copied target probe artifact
- `fidelity-analysis.json`: analyzer output, including prompt, graph, and
  KV-cache alignment status when graph metadata is present in the migration
  manifest
- `slot-probe-summary.json`: sampled target slot equality summary
- `agent-activity-resume-report.json`: optional target-side Agent Memory Graph
  resume proof when `PERMEANT_AGENT_ACTIVITY_RESUME=1`
- `agent-activity-resumed-graph.json`: optional AWS-updated graph emitted by
  the target resume proof
- `agent-activity-publish-announcement.md`: optional target-written artifact
  copied back for origin verification when publish approval is enabled
- `vllm-reverse-runtime-state.json`: optional response from the target
  `/export_reverse_runtime_state` API when `PERMEANT_REVERSE_RUNTIME_IMPORT=1`
- `mlx-reverse-import-report.json`: optional origin-side MLX import and
  continuation proof for the target-exported runtime boundary
- `origin-roundtrip-workspace/reports/roundtrip/roundtrip-report.json`:
  optional origin return-home proof when `PERMEANT_AGENT_ACTIVITY_RETURN_HOME=1`
- `origin-roundtrip-workspace/reports/roundtrip/returned-home-graph.json`:
  optional origin graph after verifying AWS evidence and continuing locally
- `target-logs/receiver.log`
- `target-logs/daemon.log`

The state directory is intentionally gitignored because it can contain transient cloud metadata and local run artifacts.

## Defaults

The default target configuration matches the validated real-runtime runs:

- region: `us-east-1`
- availability zone: `us-east-1d`
- instance type: `g4dn.xlarge`
- AMI: `ami-01011b868ec560823`
- model: `Qwen/Qwen2.5-0.5B-Instruct`
- sequence length: `2016`
- vLLM max model length: `2048`
- transfer quantization: `none`
- continuation max tokens: `16`
- fidelity horizons: `16,32,64,128`
- local MLX exporter URL: `http://127.0.0.1:29101`
- source continuation file: `/tmp/permeant-source-continuation.json`
- Agent Memory Graph manifest: unset by default; set
  `PERMEANT_AGENT_GRAPH_MANIFEST=/path/to/manifest.json` to bind graph
  metadata to the staged KV transaction
- target-side Agent Memory Graph resume: disabled by default; set
  `PERMEANT_AGENT_ACTIVITY_RESUME=1`
- approved target publish proof: disabled by default; set
  `PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH=1`
- origin return-home proof: disabled by default; set
  `PERMEANT_AGENT_ACTIVITY_RETURN_HOME=1` together with target resume and
  publish approval
- reverse runtime import proof: disabled by default; set
  `PERMEANT_REVERSE_RUNTIME_IMPORT=1` to call the live target
  `/export_reverse_runtime_state` API and import the returned vLLM decode
  boundary back into the live MLX source exporter
- local tunnel port: `39099`

For faster bootstrap, a conservative prewarmed image can be supplied through
`AWS_AMI_ID`. See `docs/aws-prewarm-image.md` for the recipe, cleanup steps,
and snapshot-storage cost guardrails. The prewarm image is only a dependency
accelerator; the runner still copies the current committed repository snapshot
to the target for each run.

Override with environment variables:

```bash
AWS_REGION=us-east-1 \
AWS_AZ=us-east-1d \
AWS_INSTANCE_TYPE=g4dn.xlarge \
PERMEANT_MODEL=Qwen/Qwen2.5-0.5B-Instruct \
PERMEANT_SEQ_LEN=2016 \
PERMEANT_VLLM_MAX_MODEL_LEN=2048 \
PERMEANT_TRANSFER_QUANTIZATION=none \
PERMEANT_CONTINUATION_MAX_TOKENS=64 \
PERMEANT_FIDELITY_HORIZONS=16,32,64 \
PERMEANT_AGENT_GRAPH_MANIFEST=/tmp/permeant-agent-graph/manifest.json \
PERMEANT_AGENT_ACTIVITY_RESUME=1 \
PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH=1 \
PERMEANT_AGENT_ACTIVITY_RETURN_HOME=1 \
PERMEANT_REVERSE_RUNTIME_IMPORT=1 \
scripts/aws-real-runtime-e2e.sh run
```

The reverse runtime proof validates target-runtime work moving back to the
origin runtime. The target exports a canonical decode boundary from the live
vLLM process, and the origin MLX exporter imports that target-generated boundary
and materializes MLX-native KV state before producing a new origin
continuation. The Agent Memory Graph return-home proof separately validates
graph, artifact, and activity continuity back on the origin.

For larger-than-2k context points, generate checked runner environment blocks
with `scripts/plan-context-benchmarks.py`; see
`docs/context-benchmark-matrix.md`. The important invariant is that
`PERMEANT_VLLM_MAX_MODEL_LEN` must be large enough for the migrated prefix,
continuation tokens, and tokenizer/runtime overhead.

## Required local preconditions

Before running:

- AWS CLI is logged into the target account
- EC2 GPU quota is high enough for `g4dn.xlarge`
- local `target/debug/permeant-cli` exists
- local MLX exporter is listening on `PERMEANT_SOURCE_URL`
- `/tmp/permeant-source-continuation.json` exists for source/target comparison
- current public IP can be reached by AWS security group ingress on SSH

Run preflight before provisioning:

```bash
scripts/aws-real-runtime-e2e.sh preflight
```

The preflight command does not create AWS resources. It validates local command
availability, numeric configuration, supported transfer quantization, local
build/source prerequisites, AWS identity, default subnet lookup, and AMI
visibility. If `PERMEANT_AGENT_GRAPH_MANIFEST` is set, preflight also verifies
that the manifest exists before any cloud resource is provisioned. It writes a
structured report to:

```text
.permeant-e2e/aws/<run-id>/preflight-report.json
```

For CI or scheduled validation that must not depend on AWS credentials or a
running local MLX source, use:

```bash
PERMEANT_PREFLIGHT_SKIP_AWS=1 \
PERMEANT_PREFLIGHT_SKIP_BUILD=1 \
PERMEANT_PREFLIGHT_SKIP_SOURCE=1 \
scripts/aws-real-runtime-e2e.sh preflight
```

Skipped checks are recorded as `skip`, not `pass`, so a scheduled report cannot
be mistaken for a full cloud-readiness proof.

## GitHub Evidence Jobs

The `Evidence Jobs` workflow has two lanes:

- a scheduled/manual non-provisioning lane that runs adapter conformance tests,
  regenerates the public evidence index, emits model/runtime validation plans,
  runs AWS preflight with AWS/build/source checks explicitly skipped, verifies
  package readiness, and uploads `permeantos-evidence-job-v0` artifacts;
- a manual-only AWS real-runtime lane that requires
  `confirm_aws_cost=RUN_AWS_REAL_RUNTIME`, the protected
  `aws-real-runtime-evidence` environment, and a self-hosted runner labelled
  `permeantos-aws-evidence`.

The scheduled lane never provisions AWS resources. The AWS lane is deliberately
not configured for GitHub-hosted runners because it requires account
credentials, source-runtime access, cleanup verification, and operator approval.
Use it only from an environment that can run the same cleanup discipline as the
local runbook.

Local equivalent:

```bash
scripts/run-evidence-job.py --mode non-provisioning --out-dir dist/evidence
```

Manual AWS equivalent:

```bash
scripts/run-evidence-job.py \
  --mode aws-real-runtime \
  --profile qwen2.5-0.5b-mlx-vllm \
  --confirm RUN_AWS_REAL_RUNTIME \
  --out-dir dist/evidence
```

## Process guarantees

The runner avoids the manual mistakes from earlier ad hoc runs:

- records the instance public IP in `state.json`
- uses the instance ID as the source of truth if the IP must be rediscovered
- copies remote setup/start scripts and executes them, instead of using fragile long inline SSH commands
- records temporary security group, key pair, PEM, known-hosts, and run artifacts
- opens the daemon tunnel using the state-file connection metadata
- always attempts artifact collection before cleanup
- always attempts cleanup from the same state file

## Cleanup and resume

If a run fails or the terminal is interrupted, run cleanup explicitly:

```bash
scripts/aws-real-runtime-e2e.sh cleanup .permeant-e2e/aws/<run-id>/state.json
```

For the latest run:

```bash
scripts/aws-real-runtime-e2e.sh cleanup
```

To inspect a run:

```bash
scripts/aws-real-runtime-e2e.sh status .permeant-e2e/aws/<run-id>/state.json
```

For the latest run:

```bash
scripts/aws-real-runtime-e2e.sh status
```

Cleanup verifies that:

- the EC2 key pair no longer exists
- the temporary security group no longer exists
- the local PEM file is removed
- the local tunnel process is stopped
- `state.json` records `cleanup_verified_at` when the cleanup verification path
  completes

AWS may still show terminated instances in the EC2 console for a while. That is normal; terminated instance rows are historical records, not billable running compute.

## Fidelity interpretation

A successful run is not enough by itself. The analyzer and slot-probe summary should be read together. The default sequence length is intentionally `2016`, not the full `2048`, so the vLLM target has enough remaining context window to generate the full 16-token continuation after its tokenizer-specific prompt expansion.

For longer-horizon fidelity checks, increase
`PERMEANT_CONTINUATION_MAX_TOKENS` and set matching
`PERMEANT_FIDELITY_HORIZONS`. The runner writes
`fidelity-horizons.json` and `fidelity-horizons.md` next to
`fidelity-analysis.json`. Larger continuation lengths require enough remaining
target context window; otherwise the horizon suite will report
`insufficient_tokens` rather than treating the run as an exact fidelity pass.
The source continuation file must also have been generated with at least the
largest requested horizon.

The current expected state after a source-exact graph-attached run is:

- migration success: `true`
- target hash verification: `true`
- written layers: `24`
- slot-probe failure count: `0`
- max sampled key/value delta: `0.0`
- post-migration continuation matches the source continuation exactly for the
  configured token horizon
- graph, KV, and prompt alignment all report `aligned` when an Agent Memory
  Graph manifest is attached

That means the transport, sampled target KV slot writes, graph binding, prefix
cache seeding, and configured continuation horizon are working for the validated
MLX-to-vLLM path.

For `PERMEANT_TRANSFER_QUANTIZATION=fp8`, strict sampled slot equality is
expected to fail because the transfer codec is lossy. Interpret quantized runs
with decode-fidelity evidence, graph/KV/prompt alignment, transaction/hash
validation, and tolerance-aware sampled deltas rather than exact sampled tensor
equality.

## Next fidelity instrumentation target

Further fidelity instrumentation should extend the target runtime state used to
attach the migrated KV cache to generation:

- request or sequence object identity
- block table selected for the continuation request
- prefix-cache ownership metadata
- sequence position and logits position
- token history used by the decode request
- whether the migrated block hash is selected for the next decode step

The goal for the next run is to explain why post-migration generation follows the target baseline even when sampled written KV slots match the source exactly.

The target runtime now emits `decode_attachment_snapshot` probe events before and after each baseline or post-migration generation call. These snapshots record:

- prompt tokenization as seen by the target runtime
- registered Permeant block hashes visible to the runtime object
- the last registered block hash and layer count
- known KV cache key and layer-map counts
- bounded summaries of vLLM objects whose names suggest scheduler, block, prefix, cache, request, token, logits, sequence, or decode state
- post-generation request/output metadata when vLLM exposes it

These events are intentionally introspective rather than prescriptive: they provide evidence about what the current `LLM.generate()` path is actually using. If the snapshots show no request/block-table/prefix state connected to the migrated hash, the next fix should move from raw KV writes to explicit decode-request attachment.

## Runner validation run

The runner was validated end to end on June 16, 2026.

Run state:

- run id: `20260616-193913`
- state directory: `.permeant-e2e/aws/20260616-193913/`
- instance id: `i-093765a58f9c7e965`
- security group: `sg-0cf3161555f8894c6`
- key pair: `permeantos-real-e2e-20260616-193913-key`
- manifest: `migration-20260616-194743-84959-manifest.json`

Process result:

- provisioning succeeded using the state-file metadata path
- SSH readiness succeeded without manual IP correction
- repository copy used `git archive`
- remote setup used the generated setup script
- target receiver/daemon startup used the generated startup script
- local SSH tunnel opened from state-file metadata
- migration completed successfully
- target probe, receiver log, daemon log, fidelity analysis, and slot-probe summary were collected
- cleanup terminated the instance, deleted the security group, deleted the key pair, removed the local PEM, and verified cleanup

Fidelity result:

- migration success: `true`
- hash validation: `true`
- written layers: `24`
- all sampled slot probes matched: `true`
- max key absolute delta: `0.0`
- max value absolute delta: `0.0`
- post-migration continuation matched the target baseline
- post-migration continuation still diverged from the source at token index `15`

This validates the operational process. The remaining work is product/runtime fidelity work, not E2E setup reliability.

## Decode-attachment instrumentation run

The decode-attachment instrumentation was validated on June 16, 2026.

Run state:

- run id: `20260616-201851`
- state directory: `.permeant-e2e/aws/20260616-201851/`
- instance id: `i-0bed64a610c85e578`
- security group: `sg-0e53b2a1a9eca95a6`
- key pair: `permeantos-real-e2e-20260616-201851-key`
- manifest: `migration-20260616-202612-19318-manifest.json`

Cleanup result:

- instance termination requested and completed
- security group deleted and verified gone
- key pair deleted and verified gone
- local PEM removed by the runner

Fidelity result:

- migration success: `true`
- hash validation: `true`
- written layers: `24`
- all sampled slot probes matched: `true`
- max key absolute delta: `0.0`
- max value absolute delta: `0.0`
- post-migration continuation still matched the target baseline
- post-migration continuation still diverged from the source at token index `15`

Decode-attachment evidence:

- `decode_attachment_snapshot_count: 4`
- stages captured:
  - `baseline_continuation:before_generate`
  - `baseline_continuation:after_generate`
  - `generate_continuation:before_generate`
  - `generate_continuation:after_generate`
- post-migration vLLM request id: `2`
- post-migration prompt token count: `6`
- post-migration prompt token ids: `[3889, 2660, 517, 3126, 41171, 21730]`
- post-migration output token ids ended with target-baseline token `32` (`A`)
- source output token ids ended with source token `2461` (`For`)
- registered Permeant block hash was visible to the runtime object: `sha256:752b47177c4c532507d41557f9c2079d59d7ae8c676281199e826a6636c76640`
- last registered layer count was `24`
- `32` candidate runtime objects were summarized, including `llm_engine`, `input_processor`, `cache_config`, `scheduler_config`, and `engine_core`

Interpretation:

The migrated block hash and exact slot writes are present in the Permeant runtime wrapper, but the post-migration `LLM.generate()` path is still creating a normal fresh vLLM request from the prompt token ids. The captured request/output metadata does not show an attachment from the generated request to the migrated block hash.

The next fix should therefore stop treating `LLM.generate([prompt])` as the post-migration decode path. Instead, the target runtime needs an explicit migrated-request attachment path that constructs or mutates the vLLM request/block-table/prefix-cache state so the next decode step selects the migrated KV block.

## Decode attachment diagnostic milestone

The real-runtime evidence now separates two concerns:

- KV transport and slot writes: the AWS target receives the migrated block, writes all expected layers into vLLM KV memory, and the slot probe can confirm sampled key/value tensors match.
- Request/decode attachment: a plain `LLM.generate([prompt])` creates a fresh vLLM request from prompt tokens, so the target records a `migrated_decode_attachment_attempt` event before post-migration generation instead of silently treating that fresh request as migrated decode.

The diagnostic event captures the migrated block-table candidate plus the reachable vLLM scheduler/cache/block-pool surface. A passing real-system milestone requires `migrated_decode_attachment_supported=true`, meaning the generated continuation request was explicitly bound to the migrated KV slots or an equivalent prefix-cache entry before decode.

## 2026-06-16 attachment-diagnostic AWS run

Run ID: `20260616-210902`
Manifest: `migration-20260616-211806-94440-manifest.json`
Instance: `g4dn.xlarge` in `us-east-1d`
Model: `Qwen/Qwen2.5-0.5B-Instruct`
Cleanup: completed; EC2 instance `i-098a8afce2f6fc415` terminated, security group `sg-0cd8c2a9991022cf8` deleted, and key pair `permeantos-real-e2e-20260616-210902-key` deleted.

Results:

- Migration completed successfully and hash verification passed.
- 24 vLLM layers were written.
- Slot probe matched all sampled key/value tensors with `max_key_abs_diff=0.0` and `max_value_abs_diff=0.0`.
- Decode snapshots were captured before/after baseline and post-migration generation.
- Post-migration output matched the target baseline exactly, but did not match the source continuation.
- `migrated_decode_attachment_supported=false`.
- Diagnostic reason: no safe public vLLM request/block-table attachment API has been identified yet for binding migrated KV slots to `LLM.generate()`.

Verdict: the cache transport and target KV write path are repeatably working on a real AWS GPU runtime, but this run still does not prove full migrated decode fidelity. The remaining milestone is explicit vLLM request/block-table or prefix-cache attachment so post-migration decode consumes the migrated KV span rather than creating a fresh request.

## Migrated decode attachment implementation path

The target runtime now attempts the first real vLLM attachment path:

- allocate physical vLLM KV blocks through `BlockPool.get_new_blocks()` instead of writing migrated bytes into slot `0` onward;
- write every migrated layer into those allocated block IDs;
- build a temporary vLLM `Request` for the continuation prompt;
- compute normal vLLM prefix block hashes for that prompt;
- seed `BlockPool.cache_full_blocks()` with the allocated migrated block IDs so the following `LLM.generate()` can discover the migrated blocks through vLLM's standard prefix-cache lookup.

For this to be meaningful, the source reference prompt must be the same full prompt that produced the migrated KV cache. Start the MLX source runtime with:

```bash
export PERMEANT_SOURCE_CONTINUATION_USE_PREFILL_PROMPT=1
```

The AWS runner now sets `PERMEANT_VLLM_CONTINUATION_PROMPT_FROM_SOURCE=1` on the target, so the copied source reference prompt becomes the target continuation prompt. A fully working run should report both `migrated_decode_attachment_supported=true` and `vllm_prefix_cache_seed_success=true`; if the prompt has fewer than one full vLLM target block, seeding will fail by design.

## Latest production transport E2E result: 2026-06-20 AWS g4dn.xlarge

Run ID: `20260620-224819`
Migration manifest: `migration-20260620-225636-64284-manifest.json`
Source runtime: local MLX, `Qwen/Qwen2.5-0.5B-Instruct`, 2016-token exported prompt/cache
Target runtime: AWS `g4dn.xlarge`, vLLM `0.23.0`, `Qwen/Qwen2.5-0.5B-Instruct`
Transport: production `wss://`/mTLS byte proxy on target port `29443`
Transfer codec: experimental `qatq`
Cleanup: AWS instance, security group, and key pair were deleted; state recorded cleanup verification at `2026-06-20T23:08:47Z`.

Observed result:

- The new default production transport path completed the real cross-host
  migration from local MLX to AWS vLLM.
- Capability exchange, encrypted USXF header verification, payload streaming,
  Agent Memory Graph binding, and two-phase commit all succeeded through WSS.
- Hash validation succeeded, vLLM prefix-cache seeding succeeded for 16 target
  blocks, and source/post-migration continuation matched exactly for 16
  generated tokens.
- The AWS target exported its decode boundary through the reverse runtime API,
  and the origin MLX runtime imported the target-advanced boundary.
- The AWS target resumed graph activity, executed approved tool work, wrote a
  new artifact, and emitted proof hash
  `sha256:b066a1dba9ed250eb54e1344c8d0092d8ad2d90dfe68bbfc1a0c740d18b6969c`.
- The origin verified the AWS-updated graph/report/artifact evidence and
  continued from the returned proof with proof hash
  `sha256:052add6058521a13902515f759499b1350d5be4055d070d4e5428a9df0adb36d`.

Transfer metrics:

- Uncompressed bytes: `49,545,216`
- Transferred bytes: `6,294,528`
- Compression ratio: `0.12704613095238096`
- Total time: `414,148.584541` ms
- Effective bandwidth: `0.00048287964700385205` Gbps

Verdict:

The preferred default production transport works for the validated
MLX-to-vLLM QATQ round-trip path. QATQ remains lossy at the tensor-slot level,
so this proof is bounded-drift plus exact observed 16-token continuation, not
bitwise tensor equality. See
`docs/aws-real-runtime-production-transport-2026-06-20.md` for the full record.

## Real-runtime E2E result: 2026-06-16 AWS g4dn.xlarge

Run ID: `20260616-223959`
Migration manifest: `migration-20260616-224810-41431-manifest.json`
Source runtime: local MLX, `Qwen/Qwen2.5-0.5B-Instruct`, 2032-token exported prompt/cache
Target runtime: AWS `g4dn.xlarge`, vLLM `0.23.0`, `Qwen/Qwen2.5-0.5B-Instruct`
Cleanup: AWS instance, security group, and key pair were deleted by the runner cleanup path.

Observed result:

- The real cross-host transport completed successfully from the local MLX source to the AWS vLLM target.
- The target registered all 24 layers and verified all migrated KV hashes.
- The direct slot probe matched exactly across all written layers: max key diff `0.0`, max value diff `0.0`.
- vLLM prefix-cache seeding succeeded for 16 migrated target blocks.
- Post-migration decode attached to the seeded vLLM prefix path and exactly matched the target baseline output.
- Source-vs-target decode fidelity still diverged after the first 11 generated tokens, so this run proves structural migration and target reuse, not bit-identical MLX-to-vLLM generation parity.

Verdict:

PermeantOS now demonstrates a real-runtime, real-target E2E migration path for this model shape: extraction, transport, target allocation, KV write, hash validation, prefix-cache attachment, and target-side decode reuse all work. The remaining gap is cross-runtime decode fidelity between MLX and vLLM, which should be treated as the next milestone rather than a transport or manifesting failure.

## Cross-runtime decode fidelity run: 2026-06-16/17

Run ID: `20260616-230743`
Migration manifest: `migration-20260616-231535-66524-manifest.json`
Source runtime: local MLX, `Qwen/Qwen2.5-0.5B-Instruct`, 2016-token exported prompt/cache
Target runtime: AWS `g4dn.xlarge`, vLLM `0.23.0`, `Qwen/Qwen2.5-0.5B-Instruct`
Cleanup: AWS instance `i-0771a38141812d025`, security group `sg-0b8e326c353d44a48`, and key pair `permeantos-real-e2e-20260616-230743-key` were cleaned up by the runner.

Observed result:

- Migration completed successfully.
- Hash validation succeeded.
- All 24 layers were written and verified.
- Slot-probe equality passed for all sampled layers: max key diff `0.0`, max value diff `0.0`.
- vLLM prefix-cache seeding succeeded for 16 migrated target blocks.
- Source continuation, post-migration vLLM continuation, and target baseline continuation all matched exactly for 16 generated tokens.
- The target prompt token count was `2016`, leaving enough room in the 2048-token vLLM context for the full continuation.

Fidelity verdict:

The previous source/target divergence was caused by context-window exhaustion at the target, not by a KV migration or decode-attachment fidelity defect. With the default sequence length reduced to `2016`, PermeantOS demonstrates full 16-token cross-runtime decode fidelity for this MLX-to-vLLM Qwen run.
