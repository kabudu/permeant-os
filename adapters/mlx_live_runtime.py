"""Self-contained live MLX runtime hook for the source exporter.

This runs a real MLX-LM model inside the exporter process, prefills a prompt,
and exposes the resulting prompt cache through the PermeantOS extractor bridge.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
import hashlib
import json

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from mlx_lm import batch_generate, load

from agent_graph_span_metadata import build_prompt_span_metadata, sha256_bytes
from mlx_runtime_bridge import AdapterError, build_extractor_response_from_cache


DEFAULT_MODEL = "gpt2"
DEFAULT_PROMPT = (
    "PermeantOS migration source runtime. "
    "This prompt is intentionally repeated to build a substantial live KV cache. "
)


class LiveRuntime:
    def __init__(self, model: Any, tokenizer: Any, prompt_text: str, prompt_tokens: list[int], caches: list[Any]):
        self.model = model
        self.tokenizer = tokenizer
        self.prompt_text = prompt_text
        self.prompt_tokens = prompt_tokens
        self.caches = caches
        self.last_reverse_import: dict[str, Any] | None = None


_RUNTIME: LiveRuntime | None = None


def _source_continuation_file() -> str | None:
    value = os.getenv("PERMEANT_SOURCE_CONTINUATION_FILE")
    if not value:
        return None
    return value


def _target_seq_len() -> int:
    return int(os.getenv("PERMEANT_MLX_TARGET_SEQ_LEN", "2048"))


def _base_prompt() -> str:
    return os.getenv("PERMEANT_MLX_BASE_PROMPT", DEFAULT_PROMPT)


def _model_id() -> str:
    return os.getenv("PERMEANT_MLX_MODEL_ID", DEFAULT_MODEL)


def _tokenizer_hash() -> str:
    explicit = os.getenv("PERMEANT_MLX_TOKENIZER_HASH")
    if explicit:
        return explicit
    return sha256_bytes(f"mlx-tokenizer:{_model_id()}".encode("utf-8"))


def _continuation_prompt() -> str | None:
    return os.getenv("PERMEANT_SOURCE_CONTINUATION_PROMPT") or os.getenv("PERMEANT_VLLM_CONTINUATION_PROMPT")


def _continuation_max_tokens() -> int:
    return int(
        os.getenv("PERMEANT_SOURCE_CONTINUATION_MAX_TOKENS")
        or os.getenv("PERMEANT_VLLM_CONTINUATION_MAX_TOKENS")
        or "16"
    )


def _encode_prompt(tokenizer: Any, prompt_text: str) -> list[int]:
    encoded = tokenizer.encode(prompt_text)
    if hasattr(encoded, "tolist"):
        encoded = encoded.tolist()
    return list(encoded)


def _decode_prompt_tokens(tokenizer: Any, prompt_tokens: list[int]) -> str | None:
    decode = getattr(tokenizer, "decode", None)
    if not callable(decode):
        return None
    decoded = decode(prompt_tokens)
    if isinstance(decoded, str):
        return decoded
    return None


def _sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _build_prompt_text(tokenizer: Any, minimum_tokens: int) -> tuple[str, list[int]]:
    seed = _base_prompt().strip()
    text = seed
    tokens = _encode_prompt(tokenizer, text)
    while len(tokens) < minimum_tokens:
        text = f"{text}\n{seed}"
        tokens = _encode_prompt(tokenizer, text)
    prefill_tokens = tokens[:minimum_tokens]
    prefill_text = _decode_prompt_tokens(tokenizer, prefill_tokens)
    return prefill_text or text, prefill_tokens


def _prefill_prompt(model: Any, tokenizer: Any, prompt_tokens: list[int]) -> list[Any]:
    response = batch_generate(
        model,
        tokenizer,
        prompts=[prompt_tokens],
        max_tokens=1,
        return_prompt_caches=True,
        verbose=False,
    )
    return response.caches[0]


def _extract_first_output_text(response: Any, prompt: str) -> str:
    candidates = []
    for attr_name in ("text", "texts", "outputs", "generations", "responses"):
        value = getattr(response, attr_name, None)
        if value is not None:
            candidates.append(value)

    for candidate_group in candidates:
        if isinstance(candidate_group, str):
            text = candidate_group
            return text[len(prompt) :] if text.startswith(prompt) else text
        if isinstance(candidate_group, list) and candidate_group:
            candidate = candidate_group[0]
            if isinstance(candidate, str):
                return candidate[len(prompt) :] if candidate.startswith(prompt) else candidate
            for attr_name in ("text", "output_text", "generated_text"):
                value = getattr(candidate, attr_name, None)
                if isinstance(value, str):
                    return value[len(prompt) :] if value.startswith(prompt) else value
    return ""


def _extract_first_output_token_ids(response: Any, tokenizer: Any, generated_text: str) -> list[int]:
    candidates = []
    for attr_name in ("token_ids", "output_ids", "generated_ids", "outputs", "generations", "responses"):
        value = getattr(response, attr_name, None)
        if value is not None:
            candidates.append(value)

    for candidate_group in candidates:
        if isinstance(candidate_group, list) and candidate_group:
            first = candidate_group[0]
            if isinstance(first, list) and all(isinstance(item, int) for item in first):
                return [int(item) for item in first]
            for attr_name in ("token_ids", "output_ids", "generated_ids"):
                value = getattr(first, attr_name, None)
                if isinstance(value, list) and all(isinstance(item, int) for item in value):
                    return [int(item) for item in value]

    if not generated_text:
        return []
    return _encode_prompt(tokenizer, generated_text)


def _materialize_reverse_runtime_state(request: dict[str, Any]) -> dict[str, Any]:
    global _RUNTIME

    runtime = get_live_runtime()
    state = request.get("reverse_runtime_state", request)
    if not isinstance(state, dict):
        raise AdapterError("reverse runtime import request must contain a JSON object")

    target_text = state.get("generated_text")
    advanced_prompt = state.get("advanced_prompt")
    base_prompt = state.get("prompt")
    if not isinstance(target_text, str) or target_text == "":
        raise AdapterError("reverse runtime state is missing target generated_text")
    if not isinstance(advanced_prompt, str) or advanced_prompt == "":
        if not isinstance(base_prompt, str) or base_prompt == "":
            raise AdapterError("reverse runtime state is missing prompt/advanced_prompt")
        advanced_prompt = base_prompt + target_text

    advanced_tokens = _encode_prompt(runtime.tokenizer, advanced_prompt)
    caches = _prefill_prompt(runtime.model, runtime.tokenizer, advanced_tokens)
    _RUNTIME = LiveRuntime(
        model=runtime.model,
        tokenizer=runtime.tokenizer,
        prompt_text=advanced_prompt,
        prompt_tokens=advanced_tokens,
        caches=caches,
    )

    response = batch_generate(
        _RUNTIME.model,
        _RUNTIME.tokenizer,
        prompts=[advanced_tokens],
        max_tokens=_continuation_max_tokens(),
        verbose=False,
    )
    origin_text = _extract_first_output_text(response, advanced_prompt)
    origin_token_ids = _extract_first_output_token_ids(response, _RUNTIME.tokenizer, origin_text)

    target_generated_token_ids = state.get("generated_token_ids")
    target_generated_token_count = len(target_generated_token_ids) if isinstance(target_generated_token_ids, list) else None
    report = {
        "schema_version": "permeantos-reverse-runtime-import-v0",
        "status": "reverse_runtime_imported",
        "reverse_runtime_imported": True,
        "model_id": _model_id(),
        "source_runtime": "mlx-live-runtime",
        "target_runtime": state.get("target_runtime"),
        "target_model_id": state.get("model_id"),
        "target_proof_hash": state.get("proof_hash"),
        "target_prompt_token_count": state.get("prompt_token_count"),
        "target_generated_token_count": target_generated_token_count,
        "origin_advanced_prompt_token_count": len(advanced_tokens),
        "origin_continuation": {
            "prompt": advanced_prompt,
            "text": origin_text,
            "token_ids": origin_token_ids,
            "token_count": len(origin_token_ids),
            "max_tokens": _continuation_max_tokens(),
        },
        "import_boundary": {
            "target_generated_text": target_text,
            "advanced_prompt_sha256": "sha256:" + hashlib.sha256(advanced_prompt.encode("utf-8")).hexdigest(),
        },
    }
    report["proof_hash"] = _sha256_json(
        {
            "schema_version": report["schema_version"],
            "target_proof_hash": report["target_proof_hash"],
            "advanced_prompt_sha256": report["import_boundary"]["advanced_prompt_sha256"],
            "origin_continuation_token_ids": origin_token_ids,
        }
    )
    _RUNTIME.last_reverse_import = report

    output_path = request.get("output_path") or os.getenv("PERMEANT_REVERSE_IMPORT_REPORT_FILE")
    if output_path:
        path = Path(str(output_path)).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _maybe_write_source_continuation(runtime: LiveRuntime) -> None:
    output_path = _source_continuation_file()
    prompt = runtime.prompt_text if os.getenv("PERMEANT_SOURCE_CONTINUATION_USE_PREFILL_PROMPT", "0") == "1" else _continuation_prompt()
    if not output_path or not prompt:
        return

    response = batch_generate(
        runtime.model,
        runtime.tokenizer,
        prompts=[_encode_prompt(runtime.tokenizer, prompt)],
        max_tokens=_continuation_max_tokens(),
        verbose=False,
    )
    generated_text = _extract_first_output_text(response, prompt)
    token_ids = _extract_first_output_token_ids(response, runtime.tokenizer, generated_text)
    prompt_token_ids = _encode_prompt(runtime.tokenizer, prompt)
    payload = {
        "prompt": prompt,
        "prompt_token_ids": prompt_token_ids,
        "prompt_token_count": len(prompt_token_ids),
        "text": generated_text,
        "token_ids": token_ids,
        "token_count": len(token_ids),
        "model_id": _model_id(),
        "max_tokens": _continuation_max_tokens(),
    }
    Path(output_path).write_text(__import__("json").dumps(payload, indent=2), encoding="utf-8")


def _ensure_runtime(minimum_tokens: int) -> LiveRuntime:
    global _RUNTIME

    if _RUNTIME is None:
        model, tokenizer = load(_model_id())
        prompt_text, prompt_tokens = _build_prompt_text(tokenizer, minimum_tokens)
        caches = _prefill_prompt(model, tokenizer, prompt_tokens)
        _RUNTIME = LiveRuntime(
            model=model,
            tokenizer=tokenizer,
            prompt_text=prompt_text,
            prompt_tokens=prompt_tokens,
            caches=caches,
        )
        _maybe_write_source_continuation(_RUNTIME)
        return _RUNTIME

    if len(_RUNTIME.prompt_tokens) < minimum_tokens:
        prompt_text, prompt_tokens = _build_prompt_text(_RUNTIME.tokenizer, minimum_tokens)
        caches = _prefill_prompt(_RUNTIME.model, _RUNTIME.tokenizer, prompt_tokens)
        _RUNTIME = LiveRuntime(
            model=_RUNTIME.model,
            tokenizer=_RUNTIME.tokenizer,
            prompt_text=prompt_text,
            prompt_tokens=prompt_tokens,
            caches=caches,
        )
        _maybe_write_source_continuation(_RUNTIME)
    return _RUNTIME


def get_live_runtime() -> LiveRuntime:
    return _ensure_runtime(_target_seq_len())


def provider(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("action") == "import_reverse_runtime_state":
        return _materialize_reverse_runtime_state(request)

    minimum_tokens = int(request.get("seq_len") or _target_seq_len())
    runtime = _ensure_runtime(minimum_tokens)
    _maybe_write_source_continuation(runtime)
    response = build_extractor_response_from_cache(
        runtime.caches,
        seq_len=minimum_tokens,
        required_tensor_names=request.get("tensor_names"),
    )
    response["agent_graph_span_metadata"] = build_prompt_span_metadata(
        prompt=runtime.prompt_text,
        token_ids=runtime.prompt_tokens[:minimum_tokens],
        tokenizer_hash=_tokenizer_hash(),
        model_id=_model_id(),
        runtime="mlx-live-runtime",
        cache_ref=os.getenv("PERMEANT_AGENT_GRAPH_CACHE_REF", "kv:mlx-live:prefill"),
    )
    return response
