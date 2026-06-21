"""Live llama.cpp state-binding hook for PermeantOS.

This hook uses the installed libllama-backed helper to import a llama.cpp
runtime state file into a fresh target context and generate continuation tokens
from that imported state. It is intentionally strict: it only claims
``used_migrated_kv=true`` when the helper reports a successful runtime-state
load and target decode.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any


def _proof_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _helper_path() -> Path:
    configured = os.getenv("PERMEANT_LLAMA_CPP_STATE_BRIDGE")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / "target" / "llamacpp_live_state_bridge"


def _model_path(payload: dict[str, Any]) -> Path:
    for candidate in (
        payload.get("model_path"),
        payload.get("model"),
        payload.get("accepted_state", {}).get("model_path")
        if isinstance(payload.get("accepted_state"), dict)
        else None,
        os.getenv("PERMEANT_LLAMA_CPP_MODEL"),
    ):
        if isinstance(candidate, str) and candidate:
            return Path(candidate).expanduser()
    raise RuntimeError("PERMEANT_LLAMA_CPP_MODEL or payload model_path is required")


def _state_path(payload: dict[str, Any]) -> Path:
    block = payload.get("block")
    if isinstance(block, dict):
        state = block.get("runtime_state")
        if isinstance(state, dict):
            path = state.get("state_file") or state.get("path")
            if isinstance(path, str) and path:
                return Path(path).expanduser()
    for candidate in (payload.get("state_file"), os.getenv("PERMEANT_LLAMA_CPP_STATE_FILE")):
        if isinstance(candidate, str) and candidate:
            return Path(candidate).expanduser()
    raise RuntimeError("llama.cpp live hook requires a runtime_state.state_file")


def _block_hash(payload: dict[str, Any]) -> str:
    block = payload.get("block")
    if isinstance(block, dict):
        value = block.get("block_hash") or block.get("hash")
        if isinstance(value, str) and value:
            return value
    accepted = payload.get("accepted_state")
    if isinstance(accepted, dict):
        value = accepted.get("hash")
        if isinstance(value, str) and value:
            return value
    hashes = payload.get("accepted_hashes")
    if isinstance(hashes, list) and hashes and isinstance(hashes[0], str):
        return hashes[0]
    raise RuntimeError("llama.cpp live hook requires a migrated block hash")


def _run_helper(args: list[str]) -> dict[str, Any]:
    helper = _helper_path()
    run = subprocess.run(
        [str(helper), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=int(os.getenv("PERMEANT_LLAMA_CPP_HOOK_TIMEOUT_SECS", "120")),
    )
    try:
        payload = json.loads(run.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"llama.cpp state helper returned non-JSON output: {run.stdout!r} {run.stderr!r}") from exc
    if run.returncode != 0 or not payload.get("success"):
        raise RuntimeError(payload.get("error") or run.stderr or "llama.cpp state helper failed")
    return payload


def _binding_proof(block_hash: str, state_file: Path, result: dict[str, Any]) -> dict[str, Any]:
    state_hash = _sha256_file(state_file)
    proof = {
        "bound_hashes": [block_hash],
        "context_id": f"llama.cpp-state:{state_hash[7:23]}",
        "kv_token_count": int(result["kv_token_count"]),
        "runtime": "llama.cpp",
        "state_file": str(state_file),
        "state_sha256": state_hash,
        "state_bytes": int(result.get("state_bytes", state_file.stat().st_size)),
    }
    proof["proof_hash"] = _proof_hash(proof)
    return proof


def hook(payload: dict[str, Any], *_args: Any) -> dict[str, Any]:
    action = payload.get("action")
    if action not in {"bind_kv_state", "verify_bound_continuation"}:
        return {"success": False, "error": f"unsupported llama.cpp live state action: {action}"}

    model = _model_path(payload)
    state_file = _state_path(payload)
    block_hash = _block_hash(payload)
    n_predict = int(os.getenv("PERMEANT_LLAMA_CPP_N_PREDICT", "8"))
    n_ctx = int(os.getenv("PERMEANT_LLAMA_CPP_CTX_SIZE", "256"))
    threads = int(os.getenv("PERMEANT_LLAMA_CPP_THREADS", "4"))

    result = _run_helper(
        [
            "--mode",
            "continue-state",
            "--model",
            str(model),
            "--state-in",
            str(state_file),
            "--n-predict",
            str(n_predict),
            "--ctx-size",
            str(n_ctx),
            "--threads",
            str(threads),
        ]
    )
    proof = _binding_proof(block_hash, state_file, result)
    if action == "bind_kv_state":
        return {
            "success": True,
            "runtime_state_bound": True,
            "binding_proof": proof,
            "helper_result": result,
        }
    return {
        "success": True,
        "binding_proof": proof,
        "continuation": {
            "token_ids": result["target_token_ids"],
            "used_migrated_kv": True,
            "binding_proof": proof,
        },
        "helper_result": result,
    }
