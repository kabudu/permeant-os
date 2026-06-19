import copy
import hashlib
import json
import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "schemas" / "agent-memory-graph-v0.schema.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "agent_memory_graph_v0.json"
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
STABLE_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]*:[A-Za-z0-9_.:-]+$")
EXPECTED_NODE_TYPES = {
    "event",
    "message",
    "tool_call",
    "tool_result",
    "plan",
    "task",
    "artifact",
    "memory",
    "retrieval",
    "summary",
    "checkpoint",
    "trace_span",
    "handoff",
    "credential_ref",
    "kv_span",
}
EXPECTED_EDGE_TYPES = {
    "caused",
    "derives_from",
    "references",
    "produced",
    "consumed",
    "supersedes",
    "resumes",
    "retrieved",
    "summarizes",
    "checkpointed",
    "handoff_to",
    "approves",
    "invalidates",
}


def load_json(path):
    return json.loads(path.read_text())


def canonical_graph_hash(graph):
    payload = copy.deepcopy(graph)
    payload.pop("graph_hash", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def test_schema_and_fixture_are_valid_json():
    schema = load_json(SCHEMA_PATH)
    fixture = load_json(FIXTURE_PATH)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["graph_version"]["const"] == fixture["graph_version"]
    assert set(schema["properties"]["nodes"]["items"]["$ref"].split("/")) >= {"node"}

    node_type_enum = set(schema["$defs"]["node"]["properties"]["type"]["enum"])
    edge_type_enum = set(schema["$defs"]["edge"]["properties"]["type"]["enum"])
    assert EXPECTED_NODE_TYPES <= node_type_enum
    assert EXPECTED_EDGE_TYPES <= edge_type_enum


def test_fixture_matches_core_agent_memory_graph_contract():
    graph = load_json(FIXTURE_PATH)

    assert set(
        ["graph_id", "graph_version", "created_at", "agent", "nodes", "edges", "kv_spans", "graph_hash"]
    ) <= set(graph)
    assert STABLE_ID_RE.match(graph["graph_id"])
    assert graph["graph_version"] == "0.1"
    assert SHA256_RE.match(graph["graph_hash"])
    assert STABLE_ID_RE.match(graph["agent"]["id"])
    assert graph["policies"]["required_approval_for_side_effects"] is True

    node_ids = {node["id"] for node in graph["nodes"]}
    assert len(node_ids) == len(graph["nodes"])

    participant_ids = {participant["id"] for participant in graph["participants"]}
    assert graph["agent"]["id"] in participant_ids

    seen_types = {node["type"] for node in graph["nodes"]}
    assert EXPECTED_NODE_TYPES <= seen_types

    for node in graph["nodes"]:
        assert STABLE_ID_RE.match(node["id"])
        assert SHA256_RE.match(node["content_hash"])
        assert "runtime" in node["provenance"]
        assert "captured_at" in node["provenance"]
        if "actor_id" in node:
            assert node["actor_id"] in participant_ids
        if "confidence" in node:
            assert 0 <= node["confidence"] <= 1

        if node["type"] == "event":
            assert node["event_kind"] in {
                "user_input",
                "system_alert",
                "scheduler_tick",
                "approval",
                "interruption",
                "cancellation",
                "webhook",
                "runtime",
            }
        elif node["type"] == "message":
            assert node["role"] in {"system", "user", "assistant", "tool"}
            assert "content" in node or "content_ref" in node
        elif node["type"] == "tool_call":
            assert node["side_effect"] in {"none", "read_only", "external_write", "unknown"}
            assert node["approval_state"] == "approved"
            assert node["resume_policy"] in {
                "retry_safe",
                "never_retry",
                "ask_user",
                "rebind",
                "compensate",
            }
            assert SHA256_RE.match(node["arguments_hash"])
            assert SHA256_RE.match(node["input_schema_hash"])
        elif node["type"] == "tool_result":
            assert SHA256_RE.match(node["result_hash"])
            assert SHA256_RE.match(node["output_schema_hash"])
            assert node["is_error"] is False
        elif node["type"] == "task":
            assert node["status"] in {
                "not_started",
                "in_progress",
                "completed",
                "failed",
                "cancelled",
                "needs_user",
            }
        elif node["type"] == "artifact":
            assert node["restore_policy"] in {
                "required",
                "optional",
                "quarantine_on_mismatch",
                "external_rebind",
            }
            assert "sha256" in node or "content_ref" in node
            assert "root_ref" in node
        elif node["type"] == "memory":
            assert node["memory_kind"] in {
                "raw_event",
                "semantic",
                "episodic",
                "procedural",
                "profile",
                "retrieval_chunk",
                "entity",
                "relationship",
                "summary",
                "vector_binding",
                "external_binding",
            }
            assert node["memory_scope"] in {"thread", "user", "org", "agent", "global", "external"}
            assert SHA256_RE.match(node["embedding_hash"])
            assert node["quality_state"] in {"active", "verified", "pinned", "archived", "suppressed", "deleted"}
            assert node["historical_state"] in {"current", "historical", "superseded"}
            assert node["trust_level"] in {"unknown", "untrusted", "derived", "operator_reviewed", "verified"}
            assert node["episode"]["continuity_state"] in {
                "open",
                "paused",
                "resumed",
                "closed",
                "recurring",
                "unknown",
            }
            assert "task" in node["episode"]["boundary_labels"]
            assert all(0 <= value <= 1 for value in node["episode"]["salience"].values())
            assert node["conflict"]["review_state"] == "needs_review"
            assert 0 <= node["conflict"]["drift_score"] <= 1
            assert node["lineage_links"][0]["node_id"] in node_ids
        elif node["type"] == "retrieval":
            assert SHA256_RE.match(node["query_hash"])
            assert node["retrieval_kind"] in {"keyword", "vector", "graph", "hybrid", "temporal", "manual"}
            assert node["planner_profile"] == "continuity_aware"
            assert node["policy_profile"] == "autonomous_agent"
            assert node["historical_mode"] == "mixed"
            assert node["graph_expansion_max_hops"] >= 0
            assert all(result["node_id"] in node_ids for result in node["results"])
            assert any("score_breakdown" in result for result in node["results"])
        elif node["type"] == "summary":
            assert node["lossy"] is True
            assert all(source_id in node_ids for source_id in node["source_node_ids"])
        elif node["type"] == "checkpoint":
            assert SHA256_RE.match(node["state_hash"])
            assert node["checkpoint_kind"] in {"session", "graph", "runtime", "store", "kv", "workflow"}
        elif node["type"] == "trace_span":
            assert node["span_kind"] in {"model", "tool", "retrieval", "orchestration", "handoff", "custom"}
            assert node["redaction_state"] == "redacted"
        elif node["type"] == "handoff":
            assert node["from_actor_id"] in participant_ids
            assert node["to_actor_id"] in participant_ids
        elif node["type"] == "credential_ref":
            serialized = json.dumps(node).lower()
            assert "secret_value" not in serialized
            assert "access_token" not in serialized
            assert "private_key" not in serialized
            assert node["redaction_state"] == "external_only"

    for edge in graph["edges"]:
        assert edge["from"] in node_ids
        assert edge["to"] in node_ids
        assert edge["type"] in EXPECTED_EDGE_TYPES

    for span in graph["kv_spans"]:
        assert span["node_id"] in node_ids
        assert span["token_end"] > span["token_start"]
        assert span["cache_ref"]
        assert SHA256_RE.match(span["tokenizer_hash"])
        assert all(SHA256_RE.match(block_hash) for block_hash in span["block_hashes"])


def test_fixture_graph_hash_is_canonical():
    graph = load_json(FIXTURE_PATH)
    assert graph["graph_hash"] == canonical_graph_hash(graph)
