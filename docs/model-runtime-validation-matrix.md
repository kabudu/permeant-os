# Model Runtime Validation Matrix

PermeantOS has one long-horizon real-runtime path today: Qwen2.5 on a local MLX
source migrated to AWS vLLM with production WSS/mTLS transport, QATQ transfer,
reverse runtime import, target-side Agent Memory Graph activity, and origin
return-home continuation. The current long-horizon AWS evidence for that path
is exact through 128 generated tokens. PermeantOS also has a raw-transfer
non-Qwen structural proof for TinyLlama on the same MLX-to-vLLM runtime path.

The next evidence step is to vary the model family and the runtime pair. This
document defines how those runs are planned so claims are not accidentally
broadened beyond the evidence.

Runtime-pair breadth should proceed in two layers. First, use the reference
PyTorch target adapter to prove that an independent target runtime accepts the
migrated state and emits auditable hash/reverse-export evidence. That path is
allowed to be slower and does not claim language decode fidelity. Then follow
with `llama.cpp` for a more practical open-source runtime story where generated
token continuation can be investigated against a real decoder.

Future model-family and runtime-breadth proofs should use raw transfer
(`PERMEANT_TRANSFER_QUANTIZATION=none`) until QATQ is perfected as a separate
codec project. Existing QATQ runs remain valid historical evidence for the
current Qwen2.5 path, but new breadth claims should not depend on that
experimental codec.

Long-horizon validation should be cost-balanced: first prove 64/128-token
continuation stability on a true local or LAN MLX-to-vLLM setup when available,
then spend AWS only on a sparse confirmation run for the most important profile.
On an Apple Silicon laptop, this usually means MLX runs locally while vLLM runs
on a nearby Linux/NVIDIA host rather than on the same machine.

## Planner

List planned profiles:

```bash
scripts/plan-model-runtime-validations.py --format json
```

Emit a preflight command for one profile:

```bash
scripts/plan-model-runtime-validations.py \
  --profile gemma-2-2b-it-mlx-vllm \
  --format shell \
  --action preflight
```

Emit the real run command:

```bash
scripts/plan-model-runtime-validations.py \
  --profile gemma-2-2b-it-mlx-vllm \
  --format shell \
  --action run
```

## Current Profiles

| Profile | Family | Model | Runtime pair | Transfer | Maturity |
|---|---|---|---|---|---|
| `qwen2.5-0.5b-mlx-vllm` | Qwen2.5 | `Qwen/Qwen2.5-0.5B-Instruct` | MLX to vLLM | `qatq` | validated |
| `qwen2.5-1.5b-mlx-vllm` | Qwen2.5 | `Qwen/Qwen2.5-1.5B-Instruct` | MLX to vLLM | `none` | next same-family |
| `qwen2.5-0.5b-long-horizon-aws` | Qwen2.5 | `Qwen/Qwen2.5-0.5B-Instruct` | MLX to vLLM | `qatq` | validated long-horizon AWS |
| `tinyllama-1.1b-chat-mlx-vllm` | Llama | `TinyLlama/TinyLlama-1.1B-Chat-v1.0` | MLX to vLLM | `none` | validated structural E2E |
| `qwen2.5-0.5b-mlx-pytorch-reference` | Qwen2.5 | `Qwen/Qwen2.5-0.5B-Instruct` | MLX to PyTorch reference | `none` | next runtime-breadth acceptance proof |
| `tinyllama-1.1b-chat-mlx-llamacpp` | Llama | `TinyLlama/TinyLlama-1.1B-Chat-v1.0` | MLX to llama.cpp | `none` | adapter implemented; raw internal KV write proven |
| `gemma-2-2b-it-mlx-vllm` | Gemma 2 | `google/gemma-2-2b-it` | MLX to vLLM | `none` | candidate new-family |
| `phi-3.5-mini-mlx-vllm` | Phi 3.5 | `microsoft/Phi-3.5-mini-instruct` | MLX to vLLM | `none` | candidate new-family |

Gemma 2 is currently gated for the available Hugging Face identity, and Phi
3.5 has a much larger raw KV shape on this bridge (`[seq, 32, 96]`) that makes
the unquantized JSON extraction path impractical at the default 2016-token
prefix. TinyLlama is the first raw-transfer non-Qwen AWS validation profile.
TinyLlama and Qwen2.5 1.5B both use a 1984-token migrated prefix to leave
extra context headroom after runtime-specific prompt re-encoding; the Qwen2.5
1.5B local source probe exported at 2016 tokens but produced zero continuation
tokens, so that length is not suitable for evidence runs. Two Qwen2.5 1.5B AWS
attempts reached target commit but failed in vLLM's FlashInfer
`BatchPrefillWithPagedKVCache` path on the T4 target for the head-dim-128
shape. An attempted `VLLM_ATTENTION_BACKEND=TRITON_ATTN` override was rejected
by vLLM `0.23.0` as an unknown environment variable, so this profile remains
an investigated-but-not-validated same-family target until the harness uses a
supported vLLM backend control or a target runtime without that kernel failure.

## Preflight Guarantees

The AWS runner now checks:

- the selected `PERMEANT_VALIDATION_PROFILE` is known, or `custom` is fully
  specified;
- the profile model matches `PERMEANT_MODEL`;
- the source and target runtime names match the selected profile;
- `PERMEANT_SEQ_LEN + PERMEANT_CONTINUATION_MAX_TOKENS` fits inside
  `PERMEANT_VLLM_MAX_MODEL_LEN`;
- transfer codec, transport, source exporter, Agent Memory Graph package, AWS
  identity, network, and AMI checks still pass.

## Evidence Rules

A profile should not be marked validated until a real run proves:

- source continuation was generated for that exact model identity;
- migrated KV state was written into the target runtime;
- target continuation matched the configured validation horizon or any mismatch
  was explained by a documented model/runtime limitation;
- reverse runtime import completed when enabled;
- Agent Memory Graph activity resumed and returned-home evidence verified when
  enabled;
- cleanup verification showed no AWS resources left running.

Reference-runtime acceptance profiles, such as the PyTorch adapter, use a
different maturity label until they include a real decoder. They may be marked
`validated acceptance proof` only when migrated tensors are materialized in the
target runtime, key/value shape and f32 fingerprints are recorded, expected
hashes verify, and reverse target state exports a proof hash. They must not be
described as decode-fidelity profiles until the target runtime generates and
compares continuation tokens.

For long-horizon claims, the run must additionally record:

- `PERMEANT_CONTINUATION_MAX_TOKENS` at or above the claimed horizon;
- `PERMEANT_FIDELITY_HORIZONS` including the claimed horizon;
- enough context-window headroom for migrated prefix plus continuation;
- exact match status, or the first mismatch index and explanation, in
  `fidelity-horizons.json` and `fidelity-horizons.md`.

## Validated Evidence

### `qwen2.5-0.5b-long-horizon-aws`

The first AWS long-horizon confirmation completed on 2026-06-21. It deliberately
shortened the migrated prefix to 1920 tokens so the 2048-token target window
could fit a 128-token continuation without context exhaustion.

| Field | Value |
| --- | --- |
| Run ID | `20260621-052744` |
| Manifest | `migration-20260621-053602-9938-manifest.json` |
| Report | `docs/aws-real-runtime-long-horizon-2026-06-21.md` |
| Transport | production `wss://`/mTLS |
| Transfer quantization | `qatq` |
| Fidelity | exact at 16, 32, 64, and 128 tokens |
| Reverse import | vLLM target boundary imported into origin MLX |
| Agent activity | target-side work plus origin return-home continuation |
| Cleanup | verified: instance terminated; temporary security group/key deleted |

### `tinyllama-1.1b-chat-mlx-vllm`

The first raw-transfer non-Qwen AWS confirmation completed on 2026-06-21. It
uses TinyLlama's Llama-family GQA shape rather than the Qwen cache geometry, so
the profile now carries explicit model cache metadata.

| Field | Value |
| --- | --- |
| Run ID | `20260621-085222` |
| Manifest | `migration-20260621-090036-99513-manifest.json` |
| Report | `docs/aws-real-runtime-tinyllama-2026-06-21.md` |
| Transport | production `wss://`/mTLS |
| Transfer quantization | `none` |
| Model cache geometry | 22 layers, 32 query heads, 4 KV heads, 64 head dim |
| KV write validation | 22 layers written; all slot probes matched |
| Target continuation | baseline/post-migration exact at 16 tokens |
| Source/target parity | not exact; first mismatch at token 0 from leading-space runtime formatting |
| Reverse import | vLLM target boundary imported into origin MLX |
| Agent activity | target-side work plus origin return-home continuation |
| Cleanup | verified: instance terminated; temporary security group/key deleted |

## Runtime-Breadth Queue

### `qwen2.5-0.5b-mlx-pytorch-reference`

This is the next runtime-pair proof. It should use raw transfer and the
reference PyTorch target adapter documented in
`docs/pytorch-target-runtime-adapter.md`.

| Field | Value |
| --- | --- |
| Goal | independent target runtime accepts migrated state |
| Source | MLX |
| Target | PyTorch reference adapter |
| Transfer quantization | `none` |
| Required evidence | accepted layer key/value tensors, f32 fingerprints, verified migrated hash, reverse export proof hash |
| Explicit non-claim | generated-token decode fidelity |

### `tinyllama-1.1b-chat-mlx-llamacpp`

The llama.cpp adapter is now implemented for accepted-state proofs, tool
capability probes, reverse export, live state-file binding, and raw internal KV
tensor writes. The state-file proof uses llama.cpp's public state-file API to
load migrated libllama state into a fresh context and decode exact matching
greedy continuation tokens. The raw internal proof uses matching private
llama.cpp headers to write canonical f32 K/V directly into `llama_kv_cache`
backend tensors; deliberate corruption changes decode, and canonical restore
returns exact source continuation.

| Field | Value |
| --- | --- |
| Local proof | `docs/llama-cpp-target-runtime-local-proof-2026-06-21.md` |
| Live binding proof | `docs/llama-cpp-live-state-binding-proof-2026-06-21.md` |
| Raw internal KV proof | `docs/llama-cpp-raw-kv-internal-write-proof-2026-06-21.md` |
| Adapter | `adapters/llamacpp_injector.py` |
| Live hook | `adapters/llamacpp_live_state_hook.py` |
| Raw bridge | `adapters/llamacpp_raw_kv_bridge.cpp` |
| Runtime tooling | `llama-cli`, `llama-server` |
| Current evidence | state-file live binding proof plus raw internal same-runtime canonical KV write proof |
| Missing for MLX/vLLM-to-llama.cpp decode claim | cross-runtime canonical KV tensor feed into the raw writer with tokenizer/span alignment and continuation validation |
