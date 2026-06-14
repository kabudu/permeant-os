"""Self-contained live MLX runtime hook for the source exporter.

This runs a real MLX-LM model inside the exporter process, prefills a prompt,
and exposes the resulting prompt cache through the PermeantOS extractor bridge.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from mlx_lm import batch_generate, load

from mlx_runtime_bridge import build_extractor_response_from_cache


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


_RUNTIME: LiveRuntime | None = None


def _target_seq_len() -> int:
    return int(os.getenv("PERMEANT_MLX_TARGET_SEQ_LEN", "2048"))


def _base_prompt() -> str:
    return os.getenv("PERMEANT_MLX_BASE_PROMPT", DEFAULT_PROMPT)


def _model_id() -> str:
    return os.getenv("PERMEANT_MLX_MODEL_ID", DEFAULT_MODEL)


def _encode_prompt(tokenizer: Any, prompt_text: str) -> list[int]:
    encoded = tokenizer.encode(prompt_text)
    if hasattr(encoded, "tolist"):
        encoded = encoded.tolist()
    return list(encoded)


def _build_prompt_text(tokenizer: Any, minimum_tokens: int) -> tuple[str, list[int]]:
    seed = _base_prompt().strip()
    text = seed
    tokens = _encode_prompt(tokenizer, text)
    while len(tokens) < minimum_tokens:
        text = f"{text}\n{seed}"
        tokens = _encode_prompt(tokenizer, text)
    return text, tokens[:minimum_tokens]


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
    return _RUNTIME


def get_live_runtime() -> LiveRuntime:
    return _ensure_runtime(_target_seq_len())


def provider(request: dict[str, Any]) -> dict[str, Any]:
    minimum_tokens = int(request.get("seq_len") or _target_seq_len())
    runtime = _ensure_runtime(minimum_tokens)
    return build_extractor_response_from_cache(
        runtime.caches,
        seq_len=minimum_tokens,
        required_tensor_names=request.get("tensor_names"),
    )
