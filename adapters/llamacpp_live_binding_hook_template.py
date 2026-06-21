"""Template for an out-of-tree llama.cpp live KV binding hook.

This file documents the PermeantOS hook contract. It deliberately does not
pretend that stock llama.cpp exposes this API today; a real implementation must
bridge into a process that can write imported KV tensors into a live
`llama_context` and force the following decode to use that bound context.
"""

from __future__ import annotations

from typing import Any

from runtime_adapter_utils import AdapterError


def hook(payload: dict[str, Any], *_args: Any) -> dict[str, Any]:
    action = payload.get("action")
    if action == "bind_kv_state":
        raise AdapterError(
            "Implement bind_kv_state by importing payload['block']['tensors'] "
            "into a live llama.cpp context and returning runtime_state_bound=true "
            "with binding_proof.bound_hashes, context_id, kv_token_count, and proof_hash."
        )
    if action == "verify_bound_continuation":
        raise AdapterError(
            "Implement verify_bound_continuation by generating from the bound "
            "llama.cpp context and returning continuation.token_ids plus "
            "continuation.used_migrated_kv=true and matching binding_proof."
        )
    raise AdapterError(f"unsupported llama.cpp live binding hook action: {action}")
