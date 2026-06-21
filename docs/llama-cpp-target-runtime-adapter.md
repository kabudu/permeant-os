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

Optional live KV import hook:

```bash
export PERMEANT_LLAMA_CPP_RUNTIME_HOOK="/ABS/PATH/my_llamacpp_runtime.py:hook"
```

The hook receives the accepted state summary and original injector request. It
should return:

```json
{"success": true, "runtime_state_bound": true}
```

For verification, the same hook may return generated continuation evidence:

```json
{"success": true, "continuation": {"token_ids": [1, 2, 3]}}
```

Only hook-backed runs that actually bind migrated KV into a live llama.cpp
context may be described as decode-continuation evidence.

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
bound context.
