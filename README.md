# permeant-os

PermeantOS is a prototype for live cross-host KV-cache migration between heterogeneous runtimes.

Key docs:
- `docs/deployment-and-testing-guide.md`: local, cloud-host, manifest, benchmark, and reusable Runpod HTTP-bridge workflow
- `docs/runpod-e2e-2026-06-14.md`: dated write-up and benchmarks from the successful MLX laptop to Runpod cross-host run on June 14, 2026
- `docs/aws-fallback-e2e-2026-06-15.md`: dated write-up and cleanup record from the successful MLX laptop to AWS fallback cross-host run on June 15, 2026
- `docs/aws-gpu-e2e-2026-06-15.md`: dated write-up and comparison table from the successful MLX laptop to AWS GPU-backed cross-host run on June 15, 2026
- `docs/aws-real-runtime-e2e-2026-06-15.md`: dated write-up from the successful MLX laptop to live in-process AWS vLLM runtime run on June 15, 2026
- `docs/aws-real-runtime-e2e-2026-06-16.md`: dated write-up from the successful MLX laptop to live in-process AWS vLLM runtime run on June 16, 2026, including the first exact source-vs-target continuation comparison
- `docs/runtime-adapter-protocol.md`: command-backed extractor/injector contract
- `docs/real-runtime-bringup.md`: next milestone plan plus the live target-runtime registration path

Benchmark snapshot:

| Run | Target | Source mode | Transport | Seq len | Total time (ms) | Effective bandwidth (Gbps) | Manifest |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| AWS GPU | `g4dn.xlarge` | live MLX | SSH tunnel to daemon | 2048 | 25245.342833 | 0.001438227963385703 | `migration-20260615-215310-60139-manifest.json` |
| AWS real runtime | `g4dn.xlarge` | live MLX | SSH tunnel to daemon + in-process vLLM hook | 2048 | 49105.921208 | 0.0016397366763484056 | `migration-20260615-232818-54818-manifest.json` |
| AWS real runtime + source compare | `g4dn.xlarge` | live MLX | SSH tunnel to daemon + in-process vLLM hook | 2048 | 222650.506042 | 0.001529894818442734 | `migration-20260616-120353-7158-manifest.json` |
| AWS CPU fallback | `t3.medium` | live MLX | SSH tunnel to daemon | 2048 | 23106.294833 | 0.0017053993142176205 | `migration-20260615-195032-6976-manifest.json` |
| Runpod live-source proof | RTX 3090 | live MLX | SSH tunnel to daemon | 2048 | 156377.4295 | 0.00011692589682723728 | `migration-20260614-154223-70658-manifest.json` |
| Runpod HTTP-bridge proof | RTX 3090 | live MLX | HTTP bridge | 2048 | 54649.212125 | 0.0016446839797195588 | `migration-20260614-195346-87816-manifest.json` |

Key adapters:
- `adapters/runpod_http_daemon_bridge.py`: carries daemon traffic through Runpod's HTTP proxy when SSH forwarding is unavailable
- `adapters/vllm_live_runtime_registry.py`: live target-runtime hook that can call into an in-process vLLM-side runtime object for registration and verification
- `adapters/vllm_real_runtime_target.py`: real in-process vLLM runtime helper that now prefers true `.kv_cache` layer paths and can compare target continuations against a source reference JSON
