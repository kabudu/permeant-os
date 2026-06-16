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
