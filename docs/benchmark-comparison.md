# Benchmark comparison snapshot

This table compares three milestone states:
- direct TCP / tunnel-backed committed run
- Runpod HTTP-bridge committed run
- future true target-runtime continuation run

Important caution:
- the first two completed rows are not perfectly apples-to-apples because the direct TCP run used FP8 transfer quantization while the HTTP-bridge run used unquantized transfer
- the point of this table is to keep the milestone progression visible, not to overfit premature transport conclusions

| Milestone | Manifest / status | Transport path | Transfer quantization | Sequence length | Transfer time (ms) | Total time (ms) | Effective bandwidth (Gbps) | Commit status | Notes |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| Direct TCP / tunnel-backed target | `migration-20260614-154223-70658` | direct daemon TCP path via local target port exposure | `fp8` | 2048 | 143485.886833 | 156377.4295 | 0.00011692589682723728 | `committed` | successful committed run before the HTTP bridge; useful proof point for the non-HTTP path |
| Runpod HTTP-bridge target | `migration-20260614-195346-87816` | daemon frames relayed through `adapters/runpod_http_daemon_bridge.py` over Runpod HTTP proxy | `none` | 2048 | 40803.50075 | 54649.212125 | 0.0016446839797195588 | `committed` | successful MLX laptop -> Runpod proof run with public HTTP reachability |
| Future true target-runtime continuation | pending | direct in-process target runtime registration | TBD | TBD | TBD | TBD | TBD | pending | should measure once a live `vllm` runtime is actually present and continuation is validated |

## Current milestone reading

What we have now:
- a successful cross-host committed run
- a reusable Runpod HTTP-bridge workflow
- a concrete in-process runtime registration adapter path
- a tensor-backed in-process demo using upstream vLLM-style cache shapes

What remains for the final milestone:
- install and run a live `vllm` runtime on the target host
- point `PERMEANT_VLLM_RUNTIME_TARGET` at that actual runtime object
- repeat the migration with the live runtime accepting block writes in-process
- measure continuation behavior and update this table with the new row

## First in-process registration demo result

Executed locally with:
- `python3 adapters/run_vllm_live_runtime_demo.py`

Observed result:
- inject result: success
- verify result: success
- written layer: `model.layers.0`
- registered hash: `sha256:demo-inprocess`
- cache snapshot confirmed non-zero key/value writes in a vLLM-style combined KV layout

Important caveat:
- this demo exercises a tensor-backed runtime object shaped after current upstream vLLM cache conventions
- it is not yet a run against the actual `vllm` Python package, because `vllm` is not installed in this environment
- that means the direct in-process registration path is now executable and proven on vLLM-style storage, while the final milestone remains the same: repeat it against a live target runtime with the real package present
