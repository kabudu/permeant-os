# AWS real-runtime E2E run - 2026-06-15

This document records the first successful cross-host run that reached a live target runtime instead of only transport-plus-staging.

Configuration:

- source host: local macOS MLX runtime on Apple Silicon
- target host: AWS `g4dn.xlarge` in `us-east-1`
- target model: `Qwen/Qwen2.5-0.5B-Instruct`
- target runtime path: in-process `vLLM` runtime hook
- manifest: `migration-20260615-232818-54818-manifest.json`

## Verdict

PermeantOS completed a real cross-host migration successfully in this configuration.

The successful run reached:

- live MLX extraction on the laptop
- transfer to the AWS daemon
- target-side live cache registration
- continuation verification against the same target runtime instance
- committed migration state
- post-verify continuation generation on the target

## Benchmark snapshot

- total time: `49105.921208 ms`
- handshake: `183.94395899999998 ms`
- header: `114.714292 ms`
- transfer: `10231.652583000001 ms`
- commit: `27594.520459000003 ms`
- effective bandwidth: `0.0016397366763484056 Gbps`
- transferred bytes: `2097152`
- compression ratio: `0.25`
- phase status: `committed`

## Target runtime probe

The target-side probe confirmed:

- `24` live layers were discovered
- the migrated block hash was registered
- verification succeeded
- a continuation probe was generated after verification

Observed continuation probe text:

```text
From Wikipedia, the free encyclopedia
Jump to: navigation, search
A
```

Observed continuation probe token ids:

```text
[271, 3830, 26587, 11, 279, 1910, 82608, 198, 33979, 311, 25, 10646, 11, 2711, 198, 32]
```

## Required target configuration

The successful AWS target path required:

- `VLLM_ENABLE_V1_MULTIPROCESSING=0`
- `PERMEANT_VLLM_CONSUMER_HOOK=/home/ubuntu/permeant-os/adapters/vllm_real_runtime_consumer.py:consume`
- `PERMEANT_VLLM_RUNTIME_TARGET=/home/ubuntu/permeant-os/adapters/vllm_real_runtime_target.py:get_runtime`
- `PERMEANT_VLLM_CONTINUATION_PROMPT="PermeantOS continuation probe"`
- `PERMEANT_VLLM_RUNTIME_TIMEOUT=300` on the daemon-side HTTP hook path

`VLLM_ENABLE_V1_MULTIPROCESSING=0` was the key switch for `vLLM 0.23.0`. Without it, `LLM(...)` used `SyncMPClient`, which hid the live KV cache behind a child engine process and made direct runtime registration impossible from the receiver hook.

## Software gaps closed during this run

The successful run required:

- in-process target runtime access
- runtime module reuse across inject and verify
- support for flattened `key_tensor` / `value_tensor` payloads
- reblocking writes from `256`-token source blocks into observed `16`-token target cache blocks
- target-side probe capture for registration, verification, and continuation

## Residual caveats

- the migration protocol metadata still reports the existing mock model identity while the source and target runtimes used live adapters
- cache discovery is functional but still noisy; the runtime helper currently sees extra non-cache candidates before narrowing to usable layer paths
- the continuation probe proves successful post-verify generation on the target runtime, but it does not yet compare source and target continuations token-for-token
