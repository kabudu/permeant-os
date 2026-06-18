# AWS fallback E2E cross-host run - June 15, 2026

This note captures the June 15, 2026 Amazon fallback run after the fresh Runpod retry was blocked from this environment and the AWS account could not yet launch GPU instances because the EC2 GPU vCPU quota was `0`.

## Outcome

Verdict:
- PermeantOS completed a real cross-host migration from the local MLX source host to a disposable Amazon EC2 target.
- The live source side extracted tensors from the local MLX exporter over the command-backed adapter seam.
- The Amazon target accepted the capability exchange, verified the encrypted header, streamed all payload blocks, and committed the migration successfully.
- All AWS resources created for the run were torn down afterward.

What this proves:
- live MLX source-process extraction
- cross-host migration from the laptop to a disposable Amazon host
- target-side header verification, block streaming, and staged import
- end-to-end commit with a captured manifest

What this does not yet prove:
- a GPU-backed AWS target run
- direct registration into a production live target inference runtime
- continuation generation from a true live target runtime

## Why this was a fallback run

Runpod retry status:
- `api.runpod.io` returned Cloudflare `403` / `1010` from the current environment before pod provisioning completed.

AWS GPU launch status:
- `g4dn.xlarge` launch attempts in `us-east-1` were blocked by account quota.
- AWS returned `VcpuLimitExceeded` because the current GPU instance bucket limit for this account was `0`.

Because of that, the practical next-best validation path was:
- keep the live local MLX source
- keep the real public-network cross-host path
- use the cheapest disposable x86 EC2 target that could run the current daemon and staged target pipeline

## Environment summary

Source host:
- OS: macOS
- Architecture: aarch64
- Runtime exposure: local MLX exporter on `127.0.0.1:29101`

Target host:
- Provider: AWS EC2
- Instance type: `t3.medium`
- Region: `us-east-1`
- OS: Amazon Linux 2023 x86_64

Transport path:
- local SSH tunnel from the laptop to the EC2 host
- daemon remained bound to `127.0.0.1:29099` on the target host

## Manifest

Saved manifest:
- `migration-20260615-195032-6976-manifest.json`

Key benchmark fields:
- `phase_status`: `committed`
- `success`: `true`
- `sequence_length`: `2048`
- `layers`: `4`
- `expected_blocks`: `8`
- `chunks_sent`: `64`
- `transferred_bytes`: `2097152`
- `handshake_time_ms`: `223.81562499999998`
- `header_time_ms`: `135.27108299999998`
- `transfer_time_ms`: `9837.705375000001`
- `commit_time_ms`: `1190.1692500000001`
- `total_time_ms`: `23106.294833`
- `effective_bandwidth_gbps`: `0.0017053993142176205`

Interpretation:
- The flow was correct and materially faster than the temporary Runpod HTTP-bridge path because this run used a direct SSH-forwarded TCP path.
- The result should still be treated as a fallback functional benchmark, not a final GPU-host benchmark.
- The target remained a staged import path rather than a fully live target-runtime continuation path.

## Target-side evidence

Observed on the EC2 target during the successful run:
- daemon accepted the capability request
- daemon verified the USXF header
- daemon streamed all payload chunks
- daemon reported `Migration COMMITTED successfully!`
- staged target artifacts were present in `/tmp/permeant-vllm-import`

Example staged files from the successful run:
- `sha256:752b47177c4c532507d41557f9c2079d59d7ae8c676281199e826a6636c76640.json`
- `sha256:752b47177c4c532507d41557f9c2079d59d7ae8c676281199e826a6636c76640.ready.json`

## Operational note: daemon hardening gap

During bring-up, a generic protocol-mismatched probe caused the daemon to exit before the next valid migration attempt.

That failure mode is now important enough to treat as part of the benchmark record:
- malformed probes and early-EOF clients should not take down the listener
- the daemon should log the failed connection and continue accepting future sessions

## Cleanup verification

Cleanup actions performed after the successful run:
- terminated the EC2 instance
- deleted the temporary security group
- deleted the temporary EC2 key pair
- stopped the local SSH tunnel
- removed temporary local AWS state artifacts

Post-run AWS verification:
- the final EC2 leftover check for the tagged test instance returned `[]`

## Required next step for a real AWS GPU rerun

The next real Amazon target run should use a GPU-backed instance only after the EC2 GPU quota is raised.

Recommended rerun target:
- `g4dn.xlarge` for cheapest-practical GPU validation

Rerun checklist:
1. Wait for the AWS GPU quota increase to be approved.
2. Launch a disposable GPU instance with SSH-only access from the laptop IP.
3. Reuse the same live MLX source runtime and direct SSH tunnel path.
4. Capture a fresh manifest and compare it against this June 15 fallback run.
