# llama.cpp Target Runtime Adapter

The llama.cpp adapter is the practical open-source runtime follow-up to the
reference PyTorch target adapter. It keeps the same evidence boundaries:

- accept migrated canonical `layer.<n>.key` and `layer.<n>.value` tensors;
- record little-endian f32 fingerprints for every accepted key/value tensor;
- verify that expected migrated block hashes were accepted;
- export auditable reverse target state;
- probe installed `llama-cli` and `llama-server` tooling.

The current in-tree adapter does not claim generated-token continuation from
migrated KV state by default. The installed llama.cpp CLI/server expose useful
runtime controls, including KV cache type options, but they do not expose a
command-line KV import API. For a real decode-fidelity claim, the adapter must
be connected to a live hook that can bind migrated KV state into a llama.cpp
context before decode.

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

The hook receives an explicit binding request:

```json
{
  "schema_version": "permeantos-llamacpp-live-kv-binding-v0",
  "action": "bind_kv_state",
  "accepted_state": {},
  "block": {
    "block_hash": "sha256:...",
    "tensors": []
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

`adapters/llamacpp_live_binding_hook_template.py` is the out-of-tree hook
template. A real hook can be implemented against a private llama.cpp wrapper,
shared library, or sidecar process before PermeantOS proposes any upstream
llama.cpp API.

## Current Local Probe

On the development host used for this adapter, `llama-cli` and `llama-server`
were available and reported:

```text
version: 8640 (7992aa7c8)
built with AppleClang 17.0.0.17000604 for Darwin arm64
```

The adapter records this information in its capability probe. Because no live
KV import hook was supplied, the local evidence status is accepted-state only.

## Evidence Criteria

Call a llama.cpp run an accepted-state proof when:

- the adapter records `target_runtime=llama.cpp`;
- the expected migrated block hash verifies;
- accepted layer summaries include key/value f32 fingerprints;
- reverse export includes the registered hash and proof hash;
- the report states `decode_claim=none-without-live-kv-import-hook`.

Call a llama.cpp run a decode-continuation proof only when a live hook binds the
migrated state into llama.cpp and returns generated token evidence from that
bound context. Upstream llama.cpp changes are intentionally deferred until this
out-of-tree binding hook proves the API shape and value.
