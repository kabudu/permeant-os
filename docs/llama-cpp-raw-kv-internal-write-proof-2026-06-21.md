# llama.cpp Raw Internal KV Write Proof - 2026-06-21

This run proves that PermeantOS can write canonical f32 KV tensors directly
into llama.cpp's internal `llama_kv_cache` backend tensors and affect real
decode output. Unlike the state-file proof, this path does not call
`llama_state_save_file` or `llama_state_load_file`.

## Runtime

| Field | Value |
| --- | --- |
| Runtime | llama.cpp |
| Installed version | `8640 (7992aa7c8)` |
| Source checkout | `ggml-org/llama.cpp` tag `b8640`, revision `7992aa7c8e21ea2eb7a5e4802da56eec7b376036` |
| Build | `AppleClang 17.0.0.17000604 for Darwin arm64` |
| Backends | BLAS, Metal, Apple M4 CPU |
| Model | `ggml-org/Qwen3-0.6B-GGUF:Q4_0` |
| GGUF path | `/Users/kabudu/.cache/huggingface/hub/models--ggml-org--Qwen3-0.6B-GGUF/snapshots/a41486f827d17edd055fe6b3b0ba3f8d427c0519/Qwen3-0.6B-Q4_0.gguf` |

## Implementation

The proof is implemented in `adapters/llamacpp_raw_kv_bridge.cpp`. It compiles
against matching llama.cpp private headers so it can access `llama_kv_cache`
internals:

- exports source-context `cache_k_l*` and `cache_v_l*` tensors as canonical f32
  rows;
- handles llama.cpp's transposed V-cache layout when `v_trans=true`;
- deliberately corrupts target K/V tensors with direct `ggml_backend_tensor_set`
  writes;
- proves decode changes after corruption;
- writes the canonical f32 source tensors directly into the fresh target
  context's internal K/V backend tensors;
- rehydrates logits by replaying only the final prompt token;
- proves restored target continuation exactly matches the source continuation.

The bridge uses explicit `llama_synchronize()` barriers around decode and
backend tensor writes. Without those barriers, Metal-backed reads/writes can
race the proof.

## Evidence

Prompt:

```text
PermeantOS raw llama.cpp KV injection proof: the agent remembers the blue key.
```

Prompt tokens:

```text
[3889, 2660, 517, 3126, 7112, 93676, 7208, 84648, 25071, 11064, 25, 279, 8315, 42357, 279, 6303, 1376, 13]
```

| Field | Value |
| --- | --- |
| `success` | `true` |
| `used_state_file` | `false` |
| `used_internal_kv_tensor_write` | `true` |
| Layer count | `28` |
| KV token count | `18` |
| First layer width | K `1024`, V `1024` |
| Canonical hash | `fnv1a64:becca9f16bc5c4da` |
| Restored hash | `fnv1a64:becca9f16bc5c4da` |
| Canonical hash exact | `true` |

Source continuation:

```text
[576, 8315, 374, 264, 3738, 11, 323, 279]
```

Continuation after deliberate raw KV corruption:

```text
[37440, 83516, 49220, 15859, 49220, 49220, 15859, 49220]
```

Continuation after direct canonical KV restore:

```text
[576, 8315, 374, 264, 3738, 11, 323, 279]
```

The proof therefore establishes both sides of the causal check:

- corrupted internal KV changes decode;
- restoring canonical f32 K/V directly into internal llama.cpp backend tensors
  restores the exact source continuation.

## Validation Commands

```bash
git clone --depth 1 --branch b8640 https://github.com/ggml-org/llama.cpp.git \
  /private/tmp/permeant-llamacpp-b8640

c++ -std=c++17 adapters/llamacpp_raw_kv_bridge.cpp \
  -o target/llamacpp_raw_kv_bridge \
  -I/private/tmp/permeant-llamacpp-b8640/src \
  -I/private/tmp/permeant-llamacpp-b8640/include \
  -I/private/tmp/permeant-llamacpp-b8640/ggml/include \
  $(pkg-config --cflags --libs llama ggml)

DYLD_LIBRARY_PATH=/opt/homebrew/lib \
target/llamacpp_raw_kv_bridge \
  --model /Users/kabudu/.cache/huggingface/hub/models--ggml-org--Qwen3-0.6B-GGUF/snapshots/a41486f827d17edd055fe6b3b0ba3f8d427c0519/Qwen3-0.6B-Q4_0.gguf \
  --prompt 'PermeantOS raw llama.cpp KV injection proof: the agent remembers the blue key.' \
  --n-predict 8 \
  --ctx-size 256 \
  --threads 4
```

## Claim Boundary

This is a raw internal llama.cpp KV tensor write proof on the same model and
runtime family. It uses private llama.cpp headers and is therefore a binding
hook/patch strategy, not a stable public llama.cpp API.

It does not yet prove MLX-to-llama.cpp or vLLM-to-llama.cpp cross-runtime
semantic parity. The next step is to feed canonical KV tensors from a different
runtime into this internal writer and validate tokenizer/span alignment,
position metadata, and continuation behavior.
