import importlib.util
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
ADAPTERS = ROOT / "adapters"
METADATA_PATH = ADAPTERS / "agent_graph_span_metadata.py"


def load_metadata():
    spec = importlib.util.spec_from_file_location("agent_graph_span_metadata", METADATA_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_builds_and_validates_prompt_bound_span_metadata():
    metadata = load_metadata()
    tokenizer_hash = metadata.sha256_bytes(b"tokenizer")
    payload = metadata.build_prompt_span_metadata(
        prompt="hello graph spans",
        token_ids=[1, 2, 3],
        tokenizer_hash=tokenizer_hash,
        model_id="model:test",
        runtime="mlx-live-runtime",
        cache_ref="kv:mlx-live:prefill",
    )

    result = metadata.validate_prompt_span_metadata(
        payload,
        expected_prompt="hello graph spans",
        expected_token_count=3,
    )

    assert result["success"] is True
    assert result["token_count"] == 3
    assert result["cache_refs"] == ["kv:mlx-live:prefill"]
    assert payload["binding"]["same_prompt_required_on_target"] is True


def test_rejects_prompt_mismatch():
    metadata = load_metadata()
    payload = metadata.build_prompt_span_metadata(
        prompt="source prompt",
        token_ids=[1, 2],
        tokenizer_hash=metadata.sha256_bytes(b"tokenizer"),
        model_id="model:test",
        runtime="mlx-live-runtime",
    )

    try:
        metadata.validate_prompt_span_metadata(payload, expected_prompt="target prompt")
    except metadata.AgentGraphSpanMetadataError as exc:
        assert "target prompt does not match" in str(exc)
    else:
        raise AssertionError("prompt mismatch should have failed validation")


def test_rejects_non_hex_hashes():
    metadata = load_metadata()

    try:
        metadata.build_prompt_span_metadata(
            prompt="source prompt",
            token_ids=[1, 2],
            tokenizer_hash="sha256:" + "z" * 64,
            model_id="model:test",
            runtime="mlx-live-runtime",
        )
    except metadata.AgentGraphSpanMetadataError as exc:
        assert "tokenizer_hash" in str(exc)
    else:
        raise AssertionError("non-hex tokenizer hash should have failed validation")


def test_validates_target_tokenizer_view():
    metadata = load_metadata()
    token_ids = [10, 20, 30]
    tokenizer_hash = metadata.sha256_bytes(b"tokenizer")
    payload = metadata.build_prompt_span_metadata(
        prompt="source prompt",
        token_ids=token_ids,
        tokenizer_hash=tokenizer_hash,
        model_id="model:test",
        runtime="mlx-live-runtime",
    )

    result = metadata.validate_prompt_span_metadata(
        payload,
        expected_token_ids=token_ids,
        expected_tokenizer_hash=tokenizer_hash,
    )

    assert result["target_tokenizer_view_verified"] is True


def test_rejects_target_token_hash_mismatch():
    metadata = load_metadata()
    payload = metadata.build_prompt_span_metadata(
        prompt="source prompt",
        token_ids=[1, 2, 3],
        tokenizer_hash=metadata.sha256_bytes(b"tokenizer"),
        model_id="model:test",
        runtime="mlx-live-runtime",
    )

    try:
        metadata.validate_prompt_span_metadata(payload, expected_token_ids=[1, 2, 4])
    except metadata.AgentGraphSpanMetadataError as exc:
        assert "target prompt token hash" in str(exc)
    else:
        raise AssertionError("target token hash mismatch should have failed validation")
