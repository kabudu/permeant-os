# llama.cpp Cross-Runtime Canonical KV Feed Proof

Date: 2026-06-21

This run proves that canonical KV tensors exported from a live MLX source
runtime can be fed directly into the llama.cpp raw internal KV writer and used
for continuation from the aligned decode boundary.

## Runtime Pair

| Field | Value |
| --- | --- |
| Source runtime | MLX-LM |
| Source model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Target runtime | llama.cpp / libllama |
| Target model | `Qwen/Qwen2.5-0.5B-Instruct-GGUF` fp16 |
| llama.cpp revision | `b8640` / `7992aa7c8e21ea2eb7a5e4802da56eec7b376036` |
| KV transport | raw canonical f32 files, no QATQ |
| Target write path | direct private-header `llama_kv_cache` backend tensor write |

## What Was Validated

- The MLX exporter wrote every layer's K/V cache as canonical f32 tensors with
  shape `[seq, kv_heads, head_dim]`.
- The llama.cpp bridge read those external tensors from a manifest rather than
  exporting source tensors from llama.cpp.
- llama.cpp tokenization of the prompt exactly matched the MLX-exported prompt
  token span.
- The bridge wrote the external canonical tensors directly into
  `cache_k_l*`/`cache_v_l*` backend tensors after deliberately corrupting the
  target KV cache.
- Corruption changed decode output.
- Restoring the MLX-exported canonical tensors produced the same greedy
  continuation token IDs as the MLX source at the aligned 17-token decode
  boundary.
- Re-exporting the target cache after write had a maximum absolute tensor
  delta of `2.98023e-08`, well inside f16-equivalent round-trip tolerance.

## Commands

Compile the proof bridge against matching llama.cpp private headers:

```sh
c++ -std=c++17 adapters/llamacpp_raw_kv_bridge.cpp \
  -o target/llamacpp_raw_kv_bridge \
  -I/private/tmp/permeant-llamacpp-b8640/src \
  -I/private/tmp/permeant-llamacpp-b8640/include \
  -I/private/tmp/permeant-llamacpp-b8640/ggml/include \
  $(pkg-config --cflags --libs llama ggml)
```

Export the live MLX canonical KV package:

```sh
.mlx-source-venv/bin/python scripts/export-mlx-canonical-kv-for-llamacpp.py \
  --model Qwen/Qwen2.5-0.5B-Instruct \
  --seq-len 17 \
  --continuation-tokens 8 \
  --output-dir /private/tmp/permeant-cross-runtime-llamacpp/qwen25-mlx-seq17
```

Feed the MLX KV package into the llama.cpp raw writer:

```sh
target/llamacpp_raw_kv_bridge \
  --model /Users/kabudu/.cache/huggingface/hub/models--Qwen--Qwen2.5-0.5B-Instruct-GGUF/snapshots/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-fp16.gguf \
  --external-kv-manifest /private/tmp/permeant-cross-runtime-llamacpp/qwen25-mlx-seq17/mlx-to-llamacpp-canonical-kv.tsv \
  --n-predict 8 \
  --ctx-size 256 \
  --threads 4
```

## Proof JSON

```json
{
  "success": true,
  "mode": "cross-runtime-canonical-kv-feed",
  "runtime": "llama.cpp",
  "source_runtime": "mlx-live-runtime",
  "source_model": "Qwen/Qwen2.5-0.5B-Instruct",
  "used_state_file": false,
  "used_internal_kv_tensor_write": true,
  "cross_runtime_canonical_kv_feed": true,
  "tokenizer_span_aligned": true,
  "position_start": 0,
  "position_count": 17,
  "prompt_tokens": [3889, 2660, 517, 3126, 11906, 2530, 15592, 13, 1096, 9934, 374, 36204, 11504, 311, 1936, 264, 11924],
  "source_token_ids": [2033, 13, 5209, 3410, 264, 11682, 16148, 315],
  "corrupt_token_ids": [99640, 99640, 321, 321, 99640, 99640, 99640, 102149],
  "restored_token_ids": [2033, 13, 5209, 3410, 264, 11682, 16148, 315],
  "corrupt_changed_continuation": true,
  "source_continuation_available": true,
  "restored_matches_source_continuation": true,
  "continuation_validated": true,
  "canonical_hash_exact": false,
  "external_hash": "fnv1a64:c84dea618d7247e9",
  "restored_hash": "fnv1a64:06b8bb2e06bfb8b1",
  "roundtrip_max_abs_delta": 2.98023e-08,
  "tensor_roundtrip_lossless_or_f16_equivalent": true,
  "layer_count": 24,
  "kv_token_count": 17,
  "first_layer": {
    "il": 0,
    "seq_len": 17,
    "k_width": 128,
    "v_width": 128
  }
}
```

## Boundary Note

An initial 18-token diagnostic run showed token/span alignment and successful
tensor feed, but the first generated token diverged while the following seven
tokens matched. Inspecting MLX-LM showed that its generation stats reported a
17-token prompt boundary for the same token-list prompt. The successful proof
therefore uses the actual MLX generation boundary: 17 prompt tokens, position
start `0`, and eight validated continuation tokens.

## Conclusion

This is the first llama.cpp proof where the source KV tensors are not produced
by llama.cpp itself. A live MLX source exported canonical KV tensors, llama.cpp
accepted them through the raw writer, and the restored target continuation
matched the MLX source continuation token-for-token at the aligned boundary.
