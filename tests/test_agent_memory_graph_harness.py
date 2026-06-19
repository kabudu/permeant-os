import importlib.util
import pathlib
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "examples" / "agent-memory-graph" / "local_agent.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("local_agent_harness", HARNESS_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_local_agent_graph_export_import_roundtrip():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        result = harness.import_session(package_dir)
        graph = harness.read_json(package_dir / "graph.json")

        assert (package_dir / "graph.json").exists()
        assert (package_dir / "manifest.json").exists()
        assert set(graph) <= {
            "graph_id",
            "graph_version",
            "created_at",
            "agent",
            "participants",
            "policies",
            "nodes",
            "edges",
            "kv_spans",
            "graph_hash",
        }
        assert result["graph_hash"] == manifest["graph_hash"]
        assert result["prompt_byte_hash"] == manifest["prompt"]["byte_hash"]
        assert result["prompt_token_hash"] == manifest["prompt"]["token_hash"]
        assert result["kv_hash"] == manifest["kv"]["kv_hash"]
        assert result["deterministic_next_response"] == manifest["deterministic_next_response"]


def test_local_agent_graph_import_rejects_artifact_tampering():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        artifact_path = package_dir / manifest["artifacts"][0]["blob_path"]
        artifact_path.write_text("tampered\n")

        try:
            harness.import_session(package_dir)
        except harness.ImportVerificationError as exc:
            assert "artifact hash mismatch" in str(exc)
        else:
            raise AssertionError("tampered artifact import should have failed")


def test_local_agent_graph_prompt_reconstruction_is_deterministic():
    harness = load_harness()
    session = harness.run_reference_session()
    prompt_a = harness.reconstruct_prompt_from_messages(session.messages)
    graph = harness.build_graph(session, harness.sha256_bytes(session.artifact_bytes), prompt_a)
    prompt_b = harness.reconstruct_prompt(graph)

    assert prompt_a == prompt_b
    assert harness.canonical_graph_hash(graph) == graph["graph_hash"]
