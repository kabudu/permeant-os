# permeant-os

PermeantOS is a prototype for live cross-host KV-cache migration between heterogeneous runtimes.

Key docs:
- `docs/deployment-and-testing-guide.md`: local, cloud-host, manifest, benchmark, and reusable Runpod HTTP-bridge workflow
- `docs/runpod-e2e-2026-06-14.md`: dated write-up and benchmarks from the successful MLX laptop to Runpod cross-host run on June 14, 2026
- `docs/aws-fallback-e2e-2026-06-15.md`: dated write-up and cleanup record from the successful MLX laptop to AWS fallback cross-host run on June 15, 2026
- `docs/runtime-adapter-protocol.md`: command-backed extractor/injector contract
- `docs/real-runtime-bringup.md`: next milestone plan plus the live target-runtime registration path

Key adapters:
- `adapters/runpod_http_daemon_bridge.py`: carries daemon traffic through Runpod's HTTP proxy when SSH forwarding is unavailable
- `adapters/vllm_live_runtime_registry.py`: live target-runtime hook that can call into an in-process vLLM-side runtime object for registration and verification
