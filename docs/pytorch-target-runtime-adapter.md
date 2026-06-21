# Reference PyTorch Target Runtime Adapter

The reference PyTorch target adapter is the next runtime-breadth step after the
validated MLX-to-vLLM path. Its purpose is narrower than vLLM continuation
fidelity: prove that an independent target runtime can accept migrated
PermeantOS KV tensors, preserve their layer/key/value structure, verify the
registered block hash, and export auditable target runtime state.

This adapter is deliberately conservative and useful for debugging:

- it accepts the same command-backed injector JSON contract as the existing
  target adapters;
- it materializes canonical `layer.<n>.key` and `layer.<n>.value` tensors as
  PyTorch tensors when `torch` is installed;
- it falls back to a list-backed runtime when PyTorch is not installed, keeping
  CI and offline adapter tests dependency-light;
- it records stable little-endian f32 SHA-256 fingerprints for each accepted
  key/value tensor;
- it exposes verification and reverse-runtime export APIs so the target-side
  state can be inspected without guessing.

The reference adapter does not claim language-model decode continuation. Its
continuation proof is an acceptance proof: the target runtime accepted the
migrated KV state and can bind that accepted state to a prompt/hash evidence
record. Actual text/token generation remains a responsibility of runtime
adapters with a decoder, such as vLLM today and llama.cpp later.

## Command-Backed Use

Use the PyTorch injector directly:

```bash
export PERMEANT_INJECTOR_MODE=json_command
export PERMEANT_INJECTOR_CMD="python3 adapters/pytorch_injector.py"
export PERMEANT_PYTORCH_RUNTIME_STATE_FILE="/tmp/permeant-pytorch-state.json"
export PERMEANT_PYTORCH_RUNTIME_PROBE_FILE="/tmp/permeant-pytorch-probe.json"
```

Or use the generic injector hook path:

```bash
export PERMEANT_INJECTOR_HOOK="/ABS/PATH/adapters/pytorch_hook_template.py:injector_hook"
export PERMEANT_PYTORCH_RUNTIME_STATE_FILE="/tmp/permeant-pytorch-state.json"
```

For `inject_block`, the adapter expects canonical tensors:

```json
{
  "action": "inject_block",
  "block_hash": "sha256:...",
  "tensors": [
    {
      "name": "layer.0.key",
      "shape": [4, 2, 64],
      "data": [0.0, 0.1]
    },
    {
      "name": "layer.0.value",
      "shape": [4, 2, 64],
      "data": [0.0, 0.1]
    }
  ]
}
```

For `verify_continuation`, the adapter checks that the block hashes were
accepted by the reference runtime or persisted state file:

```json
{
  "action": "verify_continuation",
  "expected_hashes": ["sha256:..."],
  "prompt": "same target prompt used for the migrated state"
}
```

When `prompt` is present, the adapter returns a deterministic
`continuation_proof` hash. This proves target-side binding of accepted state to
the prompt evidence record; it is not a text-generation claim.

For reverse export:

```json
{
  "action": "export_reverse_runtime_state"
}
```

The result includes `registered_hashes`, per-block layer summaries, tensor
backend, device, dtype, and a `proof_hash`.

## Evidence Criteria

Call a PyTorch reference run successful when:

- all migrated layer key/value tensor pairs are accepted;
- each key/value pair has matching canonical `[seq, kv_heads, head_dim]` shape;
- the persisted state file contains the expected migrated block hash;
- `verify_continuation` returns success for the migrated hash;
- reverse export returns a proof hash and the accepted block summaries.

Call it incomplete if the adapter only stages files without invoking the
PyTorch reference runtime hook. Call it failed if shape validation, hash
verification, or reverse export fails.

## Next Runtime Step

After PyTorch reference acceptance, the next practical open-source target is
`llama.cpp`. The llama.cpp adapter should reuse the same evidence boundaries:
accepted migrated state, hash verification, reverse export where possible, and
clear separation between state-acceptance proof and generated-token fidelity.
