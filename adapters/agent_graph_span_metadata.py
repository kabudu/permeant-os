"""Prompt-bound Agent Memory Graph span metadata for runtime adapters."""

from __future__ import annotations

import hashlib
import re
from typing import Any


SHA256_PREFIX = "sha256:"
DEFAULT_NODE_ID = "checkpoint:prompt"
DEFAULT_CACHE_REF = "kv:live-prefill:prompt"
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class AgentGraphSpanMetadataError(ValueError):
    """Raised when graph span metadata is malformed or prompt-mismatched."""


def sha256_bytes(data: bytes) -> str:
    return SHA256_PREFIX + hashlib.sha256(data).hexdigest()


def token_hash(token_ids: list[int]) -> str:
    hasher = hashlib.sha256()
    for token_id in token_ids:
        if token_id < 0:
            raise AgentGraphSpanMetadataError("token ids must be non-negative")
        hasher.update(int(token_id).to_bytes(4, byteorder="big"))
    return SHA256_PREFIX + hasher.hexdigest()


def _ensure_sha256(name: str, value: Any) -> str:
    if not isinstance(value, str) or not SHA256_RE.match(value):
        raise AgentGraphSpanMetadataError(f"{name} must be a sha256: hash")
    return value


def build_prompt_span_metadata(
    *,
    prompt: str,
    token_ids: list[int],
    tokenizer_hash: str,
    model_id: str,
    runtime: str,
    cache_ref: str = DEFAULT_CACHE_REF,
    node_id: str = DEFAULT_NODE_ID,
    block_hashes: list[str] | None = None,
) -> dict[str, Any]:
    """Build metadata tying a live prefill prompt to graph/KV span evidence."""
    if not isinstance(prompt, str) or not prompt:
        raise AgentGraphSpanMetadataError("prompt must be a non-empty string")
    if not token_ids:
        raise AgentGraphSpanMetadataError("token_ids must not be empty")
    if not isinstance(model_id, str) or not model_id:
        raise AgentGraphSpanMetadataError("model_id must be a non-empty string")
    if not isinstance(runtime, str) or not runtime:
        raise AgentGraphSpanMetadataError("runtime must be a non-empty string")
    _ensure_sha256("tokenizer_hash", tokenizer_hash)

    hashes = block_hashes or [token_hash(token_ids)]
    for index, block_hash in enumerate(hashes):
        _ensure_sha256(f"kv_spans[0].block_hashes[{index}]", block_hash)

    return {
        "version": "0.1",
        "source_runtime": runtime,
        "model_id": model_id,
        "prompt": {
            "byte_hash": sha256_bytes(prompt.encode("utf-8")),
            "token_hash": token_hash(token_ids),
            "token_count": len(token_ids),
            "tokenizer_hash": tokenizer_hash,
        },
        "kv_spans": [
            {
                "node_id": node_id,
                "token_start": 0,
                "token_end": len(token_ids),
                "cache_ref": cache_ref,
                "tokenizer_hash": tokenizer_hash,
                "block_hashes": hashes,
            }
        ],
        "binding": {
            "prompt_used_for_prefill": True,
            "same_prompt_required_on_target": True,
        },
    }


def validate_prompt_span_metadata(
    metadata: Any,
    *,
    expected_prompt: str | None = None,
    expected_token_count: int | None = None,
    expected_token_ids: list[int] | None = None,
    expected_tokenizer_hash: str | None = None,
) -> dict[str, Any]:
    """Validate graph span metadata and optional target prompt compatibility."""
    if not isinstance(metadata, dict):
        raise AgentGraphSpanMetadataError("agent_graph_span_metadata must be an object")
    if metadata.get("version") != "0.1":
        raise AgentGraphSpanMetadataError("agent_graph_span_metadata.version must be 0.1")
    if not isinstance(metadata.get("source_runtime"), str) or not metadata["source_runtime"]:
        raise AgentGraphSpanMetadataError("source_runtime must be a non-empty string")
    if not isinstance(metadata.get("model_id"), str) or not metadata["model_id"]:
        raise AgentGraphSpanMetadataError("model_id must be a non-empty string")

    prompt = metadata.get("prompt")
    if not isinstance(prompt, dict):
        raise AgentGraphSpanMetadataError("agent_graph_span_metadata.prompt must be an object")
    byte_hash = _ensure_sha256("prompt.byte_hash", prompt.get("byte_hash"))
    token_hash_value = _ensure_sha256("prompt.token_hash", prompt.get("token_hash"))
    tokenizer_hash = _ensure_sha256("prompt.tokenizer_hash", prompt.get("tokenizer_hash"))
    token_count = prompt.get("token_count")
    if not isinstance(token_count, int) or token_count <= 0:
        raise AgentGraphSpanMetadataError("prompt.token_count must be a positive integer")

    if expected_prompt is not None and sha256_bytes(expected_prompt.encode("utf-8")) != byte_hash:
        raise AgentGraphSpanMetadataError("target prompt does not match graph span prompt byte hash")
    if expected_token_count is not None and expected_token_count != token_count:
        raise AgentGraphSpanMetadataError("target prompt token count does not match graph span metadata")
    if expected_token_ids is not None:
        if not isinstance(expected_token_ids, list) or not all(isinstance(item, int) for item in expected_token_ids):
            raise AgentGraphSpanMetadataError("target prompt token ids must be an integer list")
        if len(expected_token_ids) != token_count:
            raise AgentGraphSpanMetadataError("target prompt token ids length does not match graph span metadata")
        if token_hash(expected_token_ids) != token_hash_value:
            raise AgentGraphSpanMetadataError("target prompt token hash does not match graph span metadata")
    if expected_tokenizer_hash is not None:
        _ensure_sha256("target tokenizer_hash", expected_tokenizer_hash)
        if expected_tokenizer_hash != tokenizer_hash:
            raise AgentGraphSpanMetadataError("target tokenizer hash does not match graph span metadata")

    spans = metadata.get("kv_spans")
    if not isinstance(spans, list) or not spans:
        raise AgentGraphSpanMetadataError("agent_graph_span_metadata.kv_spans must be a non-empty list")
    for index, span in enumerate(spans):
        if not isinstance(span, dict):
            raise AgentGraphSpanMetadataError(f"kv_spans[{index}] must be an object")
        if not isinstance(span.get("node_id"), str) or not span["node_id"]:
            raise AgentGraphSpanMetadataError(f"kv_spans[{index}].node_id must not be empty")
        if not isinstance(span.get("cache_ref"), str) or not span["cache_ref"]:
            raise AgentGraphSpanMetadataError(f"kv_spans[{index}].cache_ref must not be empty")
        if span.get("token_start") != 0 or span.get("token_end") != token_count:
            raise AgentGraphSpanMetadataError(f"kv_spans[{index}] must cover the full prompt token range")
        if span.get("tokenizer_hash") != tokenizer_hash:
            raise AgentGraphSpanMetadataError(f"kv_spans[{index}].tokenizer_hash must match prompt.tokenizer_hash")
        block_hashes = span.get("block_hashes")
        if not isinstance(block_hashes, list) or not block_hashes:
            raise AgentGraphSpanMetadataError(f"kv_spans[{index}].block_hashes must be a non-empty list")
        for hash_index, block_hash in enumerate(block_hashes):
            _ensure_sha256(f"kv_spans[{index}].block_hashes[{hash_index}]", block_hash)

    return {
        "success": True,
        "prompt_byte_hash": byte_hash,
        "prompt_token_hash": token_hash_value,
        "tokenizer_hash": tokenizer_hash,
        "token_count": token_count,
        "kv_span_count": len(spans),
        "cache_refs": sorted({span["cache_ref"] for span in spans}),
        "target_tokenizer_view_verified": any(
            value is not None
            for value in (
                expected_prompt,
                expected_token_count,
                expected_token_ids,
                expected_tokenizer_hash,
            )
        ),
    }
