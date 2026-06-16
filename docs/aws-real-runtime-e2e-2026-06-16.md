# AWS real-runtime E2E run - 2026-06-16

This document records the first successful cross-host run that captured an exact source-versus-target continuation comparison after a live target-runtime migration.

Configuration:

- source host: local macOS MLX runtime on Apple Silicon
- target host: AWS `g4dn.xlarge` in `us-east-1`
- target AMI: AWS deep learning base OSS NVIDIA-driver Ubuntu 22.04
- target model: `Qwen/Qwen2.5-0.5B-Instruct`
- target runtime path: in-process `vLLM` runtime hook
- manifest: `migration-20260616-120353-7158-manifest.json`

## Verdict

PermeantOS completed a real cross-host migration successfully in this configuration.

The successful run reached:

- live MLX extraction on the laptop
- transfer to the AWS daemon over a local SSH tunnel
- target-side live cache registration inside the `vLLM` runtime process
- post-migration continuation generation on the target runtime
- exact source-versus-target continuation comparison captured in the target probe
- committed migration state

## Benchmark snapshot

- total time: `222650.506042 ms`
- handshake: `176.81525000000002 ms`
- header: `282.409167 ms`
- transfer: `10966.254541 ms`
- commit: `200688.12758300002 ms`
- effective bandwidth: `0.001529894818442734 Gbps`
- transferred bytes: `2097152`
- compression ratio: `0.25`
- phase status: `committed`

Interpretation:

- transfer itself remained in the same range as the earlier successful AWS runs
- the total runtime ballooned because this fresh host paid the full cold-start cost of first-time live `vLLM` initialization, model load, KV-cache sizing, and FlashInfer warmup during commit
- this is therefore a successful functional proof, not the best steady-state latency point

## Target runtime probe

The target-side probe confirmed:

- `24` live layers were discovered
- the migrated block hash was registered
- verification succeeded
- a continuation probe was generated after verification
- a source reference JSON was loaded and compared against the target continuation

Observed target continuation text:

```text

From Wikipedia, the free encyclopedia
Jump to: navigation, search
A
```

Observed target continuation token ids:

```text
[271, 3830, 26587, 11, 279, 1910, 82608, 198, 33979, 311, 25, 10646, 11, 2711, 198, 32]
```

Observed source continuation text:

```text

From Wikipedia, the free encyclopedia
Jump to: navigation, search
For
```

Observed source continuation token ids:

```text
[271, 3830, 26587, 11, 279, 1910, 82608, 198, 33979, 311, 25, 10646, 11, 2711, 198, 2461]
```

Comparison result:

- prompt matched exactly
- the first `15` generated token ids matched
- divergence occurred at token index `15` (the 16th generated token)
- target token/text ended with `A`
- source token/text ended with `For`

What this means:

- the live cross-host migration and post-commit generation path works
- the comparison harness now gives an exact, inspectable source-versus-target fidelity signal
- continuation fidelity is close but not yet exact at this probe depth, so there is still real follow-up work on migration fidelity rather than only transport

## Operational notes

The successful AWS target path required:

- `VLLM_ENABLE_V1_MULTIPROCESSING=0`
- `PERMEANT_VLLM_CONSUMER_HOOK=/home/ubuntu/permeant-os/adapters/vllm_real_runtime_consumer.py:consume`
- `PERMEANT_VLLM_RUNTIME_TARGET=/home/ubuntu/permeant-os/adapters/vllm_real_runtime_target.py:get_runtime`
- `PERMEANT_VLLM_CONTINUATION_PROMPT="PermeantOS continuation probe"`
- `PERMEANT_SOURCE_CONTINUATION_FILE=/home/ubuntu/permeant-source-continuation.json`
- the virtualenv `bin` directory on `PATH` so the runtime hook could find `ninja`

The first failed attempt on June 16, 2026 exposed one environment gap:

- the runtime hook reached the receiver, but `vLLM` returned HTTP 500 because `ninja` was not on the process `PATH`

After restarting the receiver and daemon with:

```bash
export PATH=/home/ubuntu/permeant-os/.venv/bin:/home/ubuntu/.cargo/bin:$PATH
```

the same run path completed successfully.

## Cleanup verification

Cleanup actions performed after the successful run:

- terminated the EC2 instance
- deleted the temporary security group
- deleted the temporary EC2 key pair
- stopped the local SSH tunnel
- removed temporary local AWS connection artifacts and transfer bundles

Expected leftover state after cleanup:

- no running EC2 instance for this run
- no temporary security group
- no temporary key pair

