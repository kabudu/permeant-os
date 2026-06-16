# AWS real-runtime E2E runner

This runbook standardizes the MLX laptop to AWS `vLLM` real-runtime test path. The goal is a boring, repeatable process: provision, setup, start target services, run migration, collect artifacts, analyze fidelity, and clean up.

## Script

Use:

```bash
scripts/aws-real-runtime-e2e.sh run
```

The runner creates a per-run state directory under:

```text
.permeant-e2e/aws/<run-id>/
```

The state directory contains:

- `state.json`: AWS IDs, connection metadata, model, source URL, artifact paths
- `migration.log`: local migration output
- `vllm-runtime-probe.json`: copied target probe artifact
- `fidelity-analysis.json`: analyzer output
- `slot-probe-summary.json`: sampled target slot equality summary
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
- sequence length: `2048`
- local MLX exporter URL: `http://127.0.0.1:29101`
- source continuation file: `/tmp/permeant-source-continuation.json`
- local tunnel port: `39099`

Override with environment variables:

```bash
AWS_REGION=us-east-1 \
AWS_AZ=us-east-1d \
AWS_INSTANCE_TYPE=g4dn.xlarge \
PERMEANT_MODEL=Qwen/Qwen2.5-0.5B-Instruct \
PERMEANT_SEQ_LEN=2048 \
scripts/aws-real-runtime-e2e.sh run
```

## Required local preconditions

Before running:

- AWS CLI is logged into the target account
- EC2 GPU quota is high enough for `g4dn.xlarge`
- local `target/debug/permeant-cli` exists
- local MLX exporter is listening on `PERMEANT_SOURCE_URL`
- `/tmp/permeant-source-continuation.json` exists for source/target comparison
- current public IP can be reached by AWS security group ingress on SSH

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

AWS may still show terminated instances in the EC2 console for a while. That is normal; terminated instance rows are historical records, not billable running compute.

## Fidelity interpretation

A successful run is not enough by itself. The analyzer and slot-probe summary should be read together.

The current expected state after Run D is:

- migration success: `true`
- target hash verification: `true`
- written layers: `24`
- slot-probe failure count: `0`
- max sampled key/value delta: `0.0`
- post-migration continuation still matches target baseline, not source continuation

That means the transport and sampled target KV slot writes are working. The remaining fidelity gap is likely in decode attachment state outside the raw KV tensor values.

## Next fidelity instrumentation target

The next implementation step is to instrument the target runtime state used to attach the migrated KV cache to generation:

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
