# llama.cpp Target Runtime Adapter

The llama.cpp adapter is the practical open-source runtime follow-up to the
reference PyTorch target adapter. It keeps the same evidence boundaries:

- accept migrated canonical `layer.<n>.key` and `layer.<n>.value` tensors;
- record little-endian f32 fingerprints for every accepted key/value tensor;
- verify that expected migrated block hashes were accepted;
- export auditable reverse target state;
- probe installed `llama-cli` and `llama-server` tooling;
- optionally bind a llama.cpp runtime state file into a fresh libllama context
  and verify generated-token continuation through a live hook;
- prove raw canonical f32 K/V writes directly into llama.cpp internal
  `llama_kv_cache` backend tensors when compiled against matching private
  llama.cpp headers.

The default tensor-acceptance path does not claim generated-token continuation
from canonical migrated KV tensors. The installed llama.cpp CLI/server expose
useful runtime controls, including KV cache type options, but they do not expose
a command-line KV import API. For decode evidence, the adapter must be connected
to a live hook that can bind migrated state into a llama.cpp context before
decode. The first in-tree hook uses llama.cpp's public state-file API and is
documented in `docs/llama-cpp-live-state-binding-proof-2026-06-21.md`. The raw
internal KV proof uses private headers from the matching llama.cpp source tree
and is documented in `docs/llama-cpp-raw-kv-internal-write-proof-2026-06-21.md`.

## Command-Backed Use

```bash
export PERMEANT_INJECTOR_MODE=json_command
export PERMEANT_INJECTOR_CMD="python3 adapters/llamacpp_injector.py"
export PERMEANT_LLAMA_CPP_RUNTIME_STATE_FILE="/tmp/permeant-llamacpp-state.json"
export PERMEANT_LLAMA_CPP_RUNTIME_PROBE_FILE="/tmp/permeant-llamacpp-probe.json"
```

Optional explicit tool paths:

```bash
export PERMEANT_LLAMA_CPP_CLI="/opt/homebrew/bin/llama-cli"
export PERMEANT_LLAMA_CPP_SERVER="/opt/homebrew/bin/llama-server"
```

Optional live KV binding hook:

```bash
export PERMEANT_LLAMA_CPP_RUNTIME_HOOK="/ABS/PATH/my_llamacpp_runtime.py:hook"
```

The included live state-file hook can be used with:

```bash
export PERMEANT_LLAMA_CPP_RUNTIME_HOOK="$PWD/adapters/llamacpp_live_state_hook.py:hook"
export PERMEANT_LLAMA_CPP_STATE_BRIDGE="$PWD/target/llamacpp_live_state_bridge"
export PERMEANT_LLAMA_CPP_MODEL="/ABS/PATH/model.gguf"
export PERMEANT_LLAMA_CPP_STATE_FILE="/ABS/PATH/llama-state.bin"
```

The hook receives an explicit binding request:

```json
{
  "schema_version": "permeantos-llamacpp-live-kv-binding-v0",
  "action": "bind_kv_state",
  "accepted_state": {},
  "block": {
    "block_hash": "sha256:...",
    "tensors": [],
    "runtime_state": {
      "format": "llama.cpp-state-file",
      "state_file": "/ABS/PATH/llama-state.bin"
    }
  },
  "binding_requirements": {
    "canonical_tensor_layout": "[seq, kv_heads, head_dim]"
  }
}
```

It must return proof that the migrated KV block was actually bound into a live
llama.cpp context:

```json
{
  "success": true,
  "runtime_state_bound": true,
  "binding_proof": {
    "bound_hashes": ["sha256:..."],
    "context_id": "llama-context:...",
    "kv_token_count": 2016,
    "proof_hash": "sha256:..."
  }
}
```

For verification, the same hook receives `action=verify_bound_continuation` and
must return generated-token evidence from that bound context:

```json
{
  "success": true,
  "binding_proof": {
    "bound_hashes": ["sha256:..."],
    "context_id": "llama-context:...",
    "kv_token_count": 2016,
    "proof_hash": "sha256:..."
  },
  "continuation": {
    "token_ids": [1, 2, 3],
    "used_migrated_kv": true
  }
}
```

The adapter rejects hooks that merely report `success=true` without a binding
proof, and it rejects continuation evidence unless `used_migrated_kv=true` and
the binding proof covers the expected migrated block hash.

`adapters/llamacpp_live_state_hook.py` is the current concrete hook for
llama.cpp state files. `adapters/llamacpp_live_binding_hook_template.py`
remains the out-of-tree template for lower-level canonical KV tensor binding
against a private wrapper, shared library, sidecar process, or future upstream
llama.cpp API.

`adapters/llamacpp_raw_kv_bridge.cpp` is the current raw internal KV proof
helper. It must be compiled with `-I` paths for a matching llama.cpp source
checkout because stock installed headers keep `llama_kv_cache` opaque.

## Current Local Probe

On the development host used for this adapter, `llama-cli` and `llama-server`
were available and reported:

```text
version: 8640 (7992aa7c8)
built with AppleClang 17.0.0.17000604 for Darwin arm64
```

The adapter records this information in its capability probe. The first live
state-file proof used `ggml-org/Qwen3-0.6B-GGUF:Q4_0`, imported a saved
libllama state into a fresh target context, and produced exact matching greedy
continuation tokens:

```text
[576, 1376, 374, 264, 6303, 1376, 11, 773]
```

The proof report is
`docs/llama-cpp-live-state-binding-proof-2026-06-21.md`.

The raw internal KV proof then compiled against llama.cpp tag `b8640`, exported
canonical f32 K/V tensors from a live source context, deliberately corrupted a
fresh target context's internal K/V tensors, and restored the exact source
continuation by writing canonical f32 K/V directly into `cache_k_l*` and
`cache_v_l*` backend tensors. Its proof report is
`docs/llama-cpp-raw-kv-internal-write-proof-2026-06-21.md`.

The cross-runtime canonical KV proof uses MLX-LM as the source and llama.cpp as
the target for the same Qwen2.5 0.5B model family. MLX exports canonical f32
K/V tensors and prompt-span metadata; llama.cpp verifies that its tokenizer
produces the same prompt token span, writes the external tensors directly into
`llama_kv_cache`, observes changed decode under deliberate corruption, and
restores an eight-token greedy continuation that matches the MLX source exactly
at the aligned 17-token decode boundary. Its proof report is
`docs/llama-cpp-cross-runtime-canonical-kv-proof-2026-06-21.md`.

## Evidence Criteria

Call a llama.cpp run an accepted-state proof when:

- the adapter records `target_runtime=llama.cpp`;
- the expected migrated block hash verifies;
- accepted layer summaries include key/value f32 fingerprints;
- reverse export includes the registered hash and proof hash;
- the report states `decode_claim=none-without-live-kv-import-hook`.

Call a llama.cpp run a decode-continuation proof only when a live hook binds the
migrated state into llama.cpp and returns generated token evidence from that
bound context. The state-file hook satisfies this for llama.cpp-originated
runtime state. The raw private-header bridge now also satisfies this for
MLX-originated canonical KV at the validated Qwen2.5 decode boundary. Raw
canonical tensor import into llama.cpp internals remains a private-header
binding path until llama.cpp exposes a stable public import API.
