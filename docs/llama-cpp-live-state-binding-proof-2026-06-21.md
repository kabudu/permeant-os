# llama.cpp Live State Binding Proof - 2026-06-21

This run proves the first PermeantOS llama.cpp live runtime-state binding path
against an actual installed llama.cpp build and GGUF model. The proof uses
llama.cpp's public serialized state API as the current out-of-tree binding
surface: a source context prefills a prompt, saves runtime state, a fresh target
context loads that state, rehydrates logits by replaying only the final restored
token, and then decodes continuation tokens from the imported state.

## Runtime

| Field | Value |
| --- | --- |
| Runtime | llama.cpp |
| CLI | `/opt/homebrew/bin/llama-cli` |
| Server | `/opt/homebrew/bin/llama-server` |
| Version | `8640 (7992aa7c8)` |
| Build | `AppleClang 17.0.0.17000604 for Darwin arm64` |
| Backends | BLAS, Metal, Apple M4 CPU |
| Model | `ggml-org/Qwen3-0.6B-GGUF:Q4_0` |
| GGUF path | `/Users/kabudu/.cache/huggingface/hub/models--ggml-org--Qwen3-0.6B-GGUF/snapshots/a41486f827d17edd055fe6b3b0ba3f8d427c0519/Qwen3-0.6B-Q4_0.gguf` |

## Implementation

The proof added two files:

- `adapters/llamacpp_live_state_bridge.cpp`: a small libllama-backed helper
  that can run `roundtrip` and `continue-state` modes.
- `adapters/llamacpp_live_state_hook.py`: the PermeantOS live hook used by
  `adapters/llamacpp_injector.py` for `bind_kv_state` and
  `verify_bound_continuation`.

The adapter now accepts either canonical key/value tensors or a
`runtime_state` object. For llama.cpp live testing, the runtime state object
contains the path to a libllama state file.

## Evidence

Prompt:

```text
PermeantOS llama.cpp state migration proof: the agent remembers the blue key.
```

Source and loaded prompt tokens matched:

```text
[3889, 2660, 517, 3126, 93676, 7208, 1584, 11906, 11064, 25, 279, 8315, 42357, 279, 6303, 1376, 13]
```

The source context and fresh target context produced the same greedy
continuation after target state import:

```text
[576, 1376, 374, 264, 6303, 1376, 11, 773]
```

| Field | Value |
| --- | --- |
| `success` | `true` |
| `used_migrated_kv` | `true` |
| `continuation_exact` | `true` |
| KV token count | `17` |
| State bytes | `1,950,677` |
| State SHA-256 | `sha256:a746f5876e0c41b7b5c535a1170bb407d2e5366010c61385fb7b0cb40913486a` |
| Binding proof hash | `sha256:5bcb2eb9d8c6a6efba7d46d4ad90b746b41fe4370a447b579ec9f2b98bf44361` |
| Continuation proof hash | `sha256:33eeb7477d7113ba785154a51e631ecd8c6c4073e027eb6dafddc78b48462d51` |
| Reverse export proof hash | `sha256:c262e4c4ae57a8ecc567833a417ba3a7c7a7627531a1ea11fdb196298606db75` |

The PermeantOS command-backed adapter reported:

```text
decode_status = live_kv_binding_continuation_proven
decode_claim  = live-kv-binding-continuation-proven
```

## Claim Boundary

This is a real llama.cpp runtime-state/KV-memory binding proof. It loads
migrated libllama state into a fresh llama.cpp context and decodes from that
imported context with exact continuation-token evidence.

It is not yet a raw cross-runtime canonical tensor write directly into
llama.cpp's internal KV tensors. That lower-level API remains a future
binding/patch target if PermeantOS needs MLX/vLLM canonical KV tensors to be
written into llama.cpp without first materializing a llama.cpp state file.

## Validation Commands

```bash
c++ -std=c++17 adapters/llamacpp_live_state_bridge.cpp \
  -o target/llamacpp_live_state_bridge \
  $(pkg-config --cflags --libs llama ggml)

DYLD_LIBRARY_PATH=/opt/homebrew/lib \
target/llamacpp_live_state_bridge \
  --mode roundtrip \
  --model /Users/kabudu/.cache/huggingface/hub/models--ggml-org--Qwen3-0.6B-GGUF/snapshots/a41486f827d17edd055fe6b3b0ba3f8d427c0519/Qwen3-0.6B-Q4_0.gguf \
  --prompt 'PermeantOS llama.cpp state migration proof: the agent remembers the blue key.' \
  --state-out /private/tmp/permeant-llamacpp-live/qwen3-state.bin \
  --n-predict 8 \
  --ctx-size 256 \
  --threads 4

python3 -m unittest tests.test_llamacpp_runtime_adapter
```
