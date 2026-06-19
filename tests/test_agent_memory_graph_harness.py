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
        workspace_dir = pathlib.Path(temp_dir) / "workspace"
        manifest = harness.export_session(package_dir)
        result = harness.import_session(package_dir, workspace_dir)
        graph = harness.read_json(package_dir / "graph.json")
        restored_artifact = workspace_dir / manifest["artifacts"][0]["target_path"]

        assert (package_dir / "graph.json").exists()
        assert (package_dir / "manifest.json").exists()
        assert (package_dir / manifest["artifacts"][0]["blob_path"]).exists()
        assert manifest["artifact_store"]["layout"] == "sha256-prefix"
        assert manifest["artifacts"][0]["blob_path"].startswith("artifacts/sha256/")
        assert restored_artifact.exists()
        assert (
            harness.sha256_bytes(restored_artifact.read_bytes())
            == manifest["artifacts"][0]["sha256"]
        )
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
        assert manifest["kv_spans"] == graph["kv_spans"]
        assert manifest["kv_spans"][0]["cache_ref"] == manifest["kv"]["cache_ref"]
        assert result["restore_report"] == [
            {
                "path": manifest["artifacts"][0]["path"],
                "target_path": manifest["artifacts"][0]["target_path"],
                "status": "restored",
                "policy": "required",
                "sha256": manifest["artifacts"][0]["sha256"],
                "size_bytes": manifest["artifacts"][0]["size_bytes"],
            }
        ]
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


def test_local_agent_graph_import_rejects_unsafe_restore_path():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        manifest["artifacts"][0]["target_path"] = "../outside.json"
        harness.write_json(package_dir / "manifest.json", manifest)

        try:
            harness.import_session(package_dir, pathlib.Path(temp_dir) / "workspace")
        except harness.ImportVerificationError as exc:
            assert "unsafe artifact restore path" in str(exc)
        else:
            raise AssertionError("unsafe artifact restore path should have failed")


def test_local_agent_graph_import_rejects_unsafe_package_blob_path():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        manifest["artifacts"][0]["blob_path"] = "../outside.json"
        harness.write_json(package_dir / "manifest.json", manifest)

        try:
            harness.import_session(package_dir, pathlib.Path(temp_dir) / "workspace")
        except harness.ImportVerificationError as exc:
            assert "unsafe package path" in str(exc)
        else:
            raise AssertionError("unsafe package blob path should have failed")


def test_local_agent_graph_prompt_reconstruction_is_deterministic():
    harness = load_harness()
    session = harness.run_reference_session()
    prompt_a = harness.reconstruct_prompt_from_messages(session.messages)
    graph = harness.build_graph(session, harness.sha256_bytes(session.artifact_bytes), prompt_a)
    prompt_b = harness.reconstruct_prompt(graph)

    assert prompt_a == prompt_b
    assert harness.canonical_graph_hash(graph) == graph["graph_hash"]
