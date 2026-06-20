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


def rewrite_graph_and_manifest(harness, package_dir, graph, manifest):
    graph["graph_hash"] = harness.canonical_graph_hash(graph)
    manifest["graph_hash"] = graph["graph_hash"]
    manifest["side_effect_audit"] = harness.audit_tool_replay_safety(graph)
    if manifest.get("vector_memory", {}).get("mode") == "snapshot":
        manifest["vector_memory"] = harness.build_vector_snapshot(
            graph,
            manifest["vector_memory"]["query_text"],
        )
    manifest["security"] = harness.build_security_attestation(graph)
    harness.write_json(package_dir / "graph.json", graph)
    harness.write_json(package_dir / "manifest.json", manifest)


def first_tool_call(graph):
    return next(node for node in graph["nodes"] if node["type"] == "tool_call")


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
            "lineage",
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
        assert manifest["vector_memory"]["mode"] == "snapshot"
        assert manifest["vector_memory"]["embedding_model"] == harness.EMBEDDING_MODEL
        assert manifest["vector_memory"]["embedding_dim"] == harness.EMBEDDING_DIM
        assert manifest["vector_memory"]["expected_results"] == [
            {
                "node_id": "memory:report-fact",
                "rank": 1,
                "score": manifest["vector_memory"]["expected_results"][0]["score"],
            }
        ]
        retrieval = next(node for node in graph["nodes"] if node["id"] == "retrieval:report-memory")
        assert retrieval["retrieval_kind"] == "vector"
        assert retrieval["results"] == [
            {
                "node_id": "memory:report-fact",
                "rank": 1,
                "score": manifest["vector_memory"]["expected_results"][0]["score"],
                "score_kind": "cosine",
                "score_breakdown": [
                    {
                        "name": "semantic",
                        "value": manifest["vector_memory"]["expected_results"][0]["score"],
                        "weight": 1.0,
                    }
                ],
                "candidate_source": "semantic_neighbor",
                "snippet_hash": harness.sha256_bytes(b"artifact:report status complete"),
            }
        ]
        assert result["vector_memory"]["status"] == "verified"
        assert result["vector_memory"]["expected_results"] == manifest["vector_memory"]["expected_results"]
        assert result["security"] == {
            "status": "verified",
            "policy_version": harness.SECURITY_POLICY_VERSION,
            "signer_id": harness.TRUSTED_SIGNER_ID,
            "target_runtime": harness.RUNTIME_ID,
            "provenance_events": 1,
        }
        assert manifest["security"]["graph_root_signature"] == harness.graph_root_signature(graph["graph_hash"])
        assert manifest["security"]["policy_hooks"]["credential_policy"] == "rebind_only"
        assert manifest["side_effect_audit"] == [
            {
                "node_id": "tool:call:write-report",
                "name": "fs.write_file",
                "side_effect": "external_write",
                "status": "completed",
                "resume_policy": "never_retry",
                "approval_state": "approved",
                "action": "no_replay",
                "safe_to_import": True,
                "reason": "tool call is completed and must not be replayed",
            }
        ]
        assert result["side_effect_audit"] == manifest["side_effect_audit"]
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


def test_local_agent_graph_import_recomputes_vector_retrieval_equivalence():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        graph = harness.read_json(package_dir / "graph.json")

        result = harness.import_session(package_dir)
        expected_snapshot = harness.build_vector_snapshot(
            graph,
            manifest["vector_memory"]["query_text"],
        )

        assert result["vector_memory"]["status"] == "verified"
        assert result["vector_memory"]["expected_results"] == expected_snapshot["expected_results"]
        assert result["vector_memory"]["query_hash"] == expected_snapshot["query_hash"]


def test_local_agent_graph_import_rejects_vector_embedding_model_mismatch():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        manifest["vector_memory"]["embedding_model"] = "other-embedding-model"
        harness.write_json(package_dir / "manifest.json", manifest)

        try:
            harness.import_session(package_dir)
        except harness.ImportVerificationError as exc:
            assert "embedding model mismatch" in str(exc)
        else:
            raise AssertionError("embedding model mismatch should have failed")


def test_local_agent_graph_import_rejects_memory_node_embedding_hash_mismatch():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        graph = harness.read_json(package_dir / "graph.json")
        memory = next(node for node in graph["nodes"] if node["id"] == "memory:report-fact")
        memory["embedding_hash"] = harness.sha256_bytes(b"wrong-memory-embedding")
        rewrite_graph_and_manifest(harness, package_dir, graph, manifest)

        try:
            harness.import_session(package_dir)
        except harness.ImportVerificationError as exc:
            assert "memory node embedding hash mismatch" in str(exc)
        else:
            raise AssertionError("memory node embedding hash mismatch should have failed")


def test_local_agent_graph_import_rejects_vector_retrieval_mismatch():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        manifest["vector_memory"]["expected_results"][0]["score"] = -1.0
        harness.write_json(package_dir / "manifest.json", manifest)

        try:
            harness.import_session(package_dir)
        except harness.ImportVerificationError as exc:
            assert "vector retrieval results mismatch" in str(exc)
        else:
            raise AssertionError("vector retrieval mismatch should have failed")


def test_local_agent_graph_import_rejects_vector_retrieval_node_mismatch():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        graph = harness.read_json(package_dir / "graph.json")
        retrieval = next(node for node in graph["nodes"] if node["id"] == "retrieval:report-memory")
        retrieval["results"][0]["score"] = -1.0
        rewrite_graph_and_manifest(harness, package_dir, graph, manifest)

        try:
            harness.import_session(package_dir)
        except harness.ImportVerificationError as exc:
            assert "retrieval node retrieval:report-memory does not match vector snapshot results" in str(exc)
        else:
            raise AssertionError("vector retrieval node mismatch should have failed")


def test_local_agent_graph_import_reports_external_vector_rebind_required():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        manifest["vector_memory"] = {
            "mode": "external_rebind",
            "vector_store_ref": "vector:hosted:customer-memory",
            "embedding_model": harness.EMBEDDING_MODEL,
            "embedding_dim": harness.EMBEDDING_DIM,
            "rebind_required": True,
        }
        harness.write_json(package_dir / "manifest.json", manifest)

        result = harness.import_session(package_dir)

        assert result["vector_memory"] == {
            "status": "rebind_required",
            "vector_store_ref": "vector:hosted:customer-memory",
            "embedding_model": harness.EMBEDDING_MODEL,
        }


def test_local_agent_graph_import_rejects_external_vector_without_rebind_marker():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        manifest["vector_memory"] = {
            "mode": "external_rebind",
            "vector_store_ref": "vector:hosted:customer-memory",
            "embedding_model": harness.EMBEDDING_MODEL,
            "embedding_dim": harness.EMBEDDING_DIM,
        }
        harness.write_json(package_dir / "manifest.json", manifest)

        try:
            harness.import_session(package_dir)
        except harness.ImportVerificationError as exc:
            assert "external vector memory must be explicitly marked rebind_required" in str(exc)
        else:
            raise AssertionError("external vector memory without rebind marker should have failed")


def test_local_agent_graph_import_rejects_tampered_graph_root_signature():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        manifest["security"]["graph_root_signature"] = harness.sha256_bytes(b"tampered-signature")
        harness.write_json(package_dir / "manifest.json", manifest)

        try:
            harness.import_session(package_dir)
        except harness.ImportVerificationError as exc:
            assert "graph root signature mismatch" in str(exc)
        else:
            raise AssertionError("tampered graph root signature should have failed")


def test_local_agent_graph_import_rejects_raw_secret_material():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        graph = harness.read_json(package_dir / "graph.json")
        credential = next(node for node in graph["nodes"] if node["type"] == "credential_ref")
        credential["secret_value"] = "not-for-export"
        rewrite_graph_and_manifest(harness, package_dir, graph, manifest)

        try:
            harness.import_session(package_dir)
        except harness.ImportVerificationError as exc:
            assert "raw secret material is not allowed" in str(exc)
            assert "secret_value" in str(exc)
        else:
            raise AssertionError("raw secret material should have failed")


def test_local_agent_graph_import_rejects_untrusted_target_runtime():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        harness.export_session(package_dir)

        try:
            harness.import_session(package_dir, target_runtime="runtime:untrusted")
        except harness.ImportVerificationError as exc:
            assert "target runtime is not allowed by security policy" in str(exc)
        else:
            raise AssertionError("untrusted target runtime should have failed")


def test_local_agent_graph_import_rejects_disallowed_tool():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        graph = harness.read_json(package_dir / "graph.json")
        tool_call = first_tool_call(graph)
        tool_call["name"] = "shell.exec"
        rewrite_graph_and_manifest(harness, package_dir, graph, manifest)

        try:
            harness.import_session(package_dir)
        except harness.ImportVerificationError as exc:
            assert "tool is not allowed by security policy" in str(exc)
        else:
            raise AssertionError("disallowed tool should have failed")


def test_local_agent_graph_import_rejects_disallowed_artifact_path():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        manifest["artifacts"][0]["path"] = "secrets/result.json"
        manifest["security"] = harness.build_security_attestation(harness.read_json(package_dir / "graph.json"))
        harness.write_json(package_dir / "manifest.json", manifest)

        try:
            harness.import_session(package_dir)
        except harness.ImportVerificationError as exc:
            assert "artifact path is not allowed by security policy" in str(exc)
        else:
            raise AssertionError("disallowed artifact path should have failed")


def test_local_agent_graph_import_rejects_credential_ref_without_external_rebind():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        graph = harness.read_json(package_dir / "graph.json")
        credential = next(node for node in graph["nodes"] if node["type"] == "credential_ref")
        credential["redaction_state"] = "none"
        rewrite_graph_and_manifest(harness, package_dir, graph, manifest)

        try:
            harness.import_session(package_dir)
        except harness.ImportVerificationError as exc:
            assert "credential reference must be external_only" in str(exc)
        else:
            raise AssertionError("credential ref without external rebind should have failed")


def test_local_agent_graph_import_preserves_completed_cloud_write_without_replay():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        workspace_dir = pathlib.Path(temp_dir) / "workspace"
        manifest = harness.export_session(package_dir)
        graph = harness.read_json(package_dir / "graph.json")
        tool_call = first_tool_call(graph)
        tool_call["name"] = "aws.ec2.run_instances"
        tool_call["provider"] = "aws"
        tool_call["external_resource_ids"] = ["aws:ec2:instance/i-1234567890abcdef0"]
        tool_call["side_effect"] = "external_write"
        tool_call["status"] = "completed"
        tool_call["resume_policy"] = "never_retry"
        tool_call["approval_state"] = "approved"
        rewrite_graph_and_manifest(harness, package_dir, graph, manifest)

        result = harness.import_session(package_dir, workspace_dir)

        assert result["side_effect_audit"][0]["action"] == "no_replay"
        assert result["side_effect_audit"][0]["safe_to_import"] is True
        assert result["side_effect_audit"][0]["name"] == "aws.ec2.run_instances"


def test_local_agent_graph_import_allows_pending_read_only_retry_safe_tool():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        graph = harness.read_json(package_dir / "graph.json")
        tool_call = first_tool_call(graph)
        tool_call["name"] = "aws.ec2.describe_instances"
        tool_call["side_effect"] = "read_only"
        tool_call["status"] = "in_progress"
        tool_call["resume_policy"] = "retry_safe"
        tool_call["approval_state"] = "not_required"
        rewrite_graph_and_manifest(harness, package_dir, graph, manifest)

        result = harness.import_session(package_dir)

        assert result["side_effect_audit"][0]["action"] == "retry_allowed"
        assert result["side_effect_audit"][0]["safe_to_import"] is True


def test_local_agent_graph_import_requires_manual_policy_for_pending_external_write():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        graph = harness.read_json(package_dir / "graph.json")
        tool_call = first_tool_call(graph)
        tool_call["name"] = "aws.ec2.run_instances"
        tool_call["side_effect"] = "external_write"
        tool_call["status"] = "in_progress"
        tool_call["resume_policy"] = "ask_user"
        tool_call["approval_state"] = "requested"
        rewrite_graph_and_manifest(harness, package_dir, graph, manifest)

        result = harness.import_session(package_dir)

        assert result["side_effect_audit"][0]["action"] == "requires_user"
        assert result["side_effect_audit"][0]["safe_to_import"] is True


def test_local_agent_graph_import_rejects_unsafe_pending_external_write_retry():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        graph = harness.read_json(package_dir / "graph.json")
        tool_call = first_tool_call(graph)
        tool_call["name"] = "aws.ec2.run_instances"
        tool_call["side_effect"] = "external_write"
        tool_call["status"] = "in_progress"
        tool_call["resume_policy"] = "retry_safe"
        tool_call["approval_state"] = "approved"
        rewrite_graph_and_manifest(harness, package_dir, graph, manifest)

        try:
            harness.import_session(package_dir)
        except harness.ImportVerificationError as exc:
            assert "unsafe tool replay policy" in str(exc)
            assert "pending side-effecting tool call is not safe to replay automatically" in str(exc)
        else:
            raise AssertionError("unsafe pending external write replay should have failed")


def test_local_agent_graph_import_rejects_expired_pending_tool_approval():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        graph = harness.read_json(package_dir / "graph.json")
        tool_call = first_tool_call(graph)
        tool_call["side_effect"] = "external_write"
        tool_call["status"] = "needs_user"
        tool_call["resume_policy"] = "ask_user"
        tool_call["approval_state"] = "expired"
        rewrite_graph_and_manifest(harness, package_dir, graph, manifest)

        try:
            harness.import_session(package_dir)
        except harness.ImportVerificationError as exc:
            assert "approval is expired" in str(exc)
        else:
            raise AssertionError("pending tool call with expired approval should have failed")


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


def test_local_agent_graph_redacted_artifact_requires_rebind_without_blob():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        workspace_dir = pathlib.Path(temp_dir) / "workspace"
        policy = harness.ArtifactExportPolicy(redact_paths={"reports/result.json"})
        manifest = harness.export_session(package_dir, policy)
        result = harness.import_session(package_dir, workspace_dir)
        graph = harness.read_json(package_dir / "graph.json")
        artifact = manifest["artifacts"][0]
        artifact_node = next(node for node in graph["nodes"] if node["id"] == "artifact:report")

        assert artifact["restore_policy"] == "external_rebind"
        assert artifact["rebind_required"] is True
        assert artifact["packaging"] == "redacted"
        assert "blob_path" not in artifact
        assert not (package_dir / "artifacts").exists()
        assert manifest["artifact_policy"]["redacted_artifacts"] == [
            {"path": "reports/result.json", "reason": "export_policy"}
        ]
        assert artifact_node["redaction_state"] == "redacted"
        assert artifact_node["restore_policy"] == "external_rebind"
        assert result["verified_artifacts"] == [
            {
                "path": "reports/result.json",
                "sha256": artifact["sha256"],
                "status": "rebind_required",
                "policy": "external_rebind",
            }
        ]
        assert result["restore_report"] == [
            {
                "path": "reports/result.json",
                "status": "rebind_required",
                "policy": "external_rebind",
                "sha256": artifact["sha256"],
            }
        ]
        assert not (workspace_dir / "reports" / "result.json").exists()


def test_local_agent_graph_excluded_artifact_requires_rebind_without_blob():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        policy = harness.ArtifactExportPolicy(exclude_paths={"reports/result.json"})
        manifest = harness.export_session(package_dir, policy)
        graph = harness.read_json(package_dir / "graph.json")
        artifact = manifest["artifacts"][0]
        artifact_node = next(node for node in graph["nodes"] if node["id"] == "artifact:report")

        assert artifact["restore_policy"] == "external_rebind"
        assert artifact["rebind_required"] is True
        assert artifact["packaging"] == "excluded"
        assert "blob_path" not in artifact
        assert not (package_dir / "artifacts").exists()
        assert manifest["artifact_policy"]["excluded_artifacts"] == [
            {"path": "reports/result.json", "reason": "export_policy"}
        ]
        assert artifact_node["redaction_state"] == "external_only"
        assert artifact_node["artifact_kind"] == "external"


def test_local_agent_graph_import_rejects_unresolved_artifact_without_rebind_policy():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        manifest = harness.export_session(package_dir)
        manifest["artifacts"][0].pop("blob_path")
        harness.write_json(package_dir / "manifest.json", manifest)

        try:
            harness.import_session(package_dir)
        except harness.ImportVerificationError as exc:
            assert "unresolved artifact is not explicitly rebindable" in str(exc)
        else:
            raise AssertionError("unresolved non-rebindable artifact should have failed")


def test_local_agent_graph_import_rejects_rebind_artifact_without_explicit_marker():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        policy = harness.ArtifactExportPolicy(redact_paths={"reports/result.json"})
        manifest = harness.export_session(package_dir, policy)
        manifest["artifacts"][0].pop("rebind_required")
        harness.write_json(package_dir / "manifest.json", manifest)

        try:
            harness.import_session(package_dir)
        except harness.ImportVerificationError as exc:
            assert "explicitly marked rebindable" in str(exc)
        else:
            raise AssertionError("external artifact without rebind marker should have failed")


def test_local_agent_graph_restores_large_artifact_blob():
    harness = load_harness()
    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        workspace_dir = pathlib.Path(temp_dir) / "workspace"
        manifest = harness.export_session(package_dir)
        artifact = manifest["artifacts"][0]
        large_payload = b"permeant-large-artifact\n" * 100_000
        large_hash = harness.sha256_bytes(large_payload)
        large_blob_path = harness.content_addressed_blob_path(large_hash, artifact["path"])
        large_blob = package_dir / large_blob_path
        large_blob.parent.mkdir(parents=True, exist_ok=True)
        large_blob.write_bytes(large_payload)
        old_blob = package_dir / artifact["blob_path"]
        old_blob.unlink()

        artifact["blob_path"] = large_blob_path
        artifact["sha256"] = large_hash
        artifact["size_bytes"] = len(large_payload)
        manifest["deterministic_next_response"] = harness.deterministic_continue(
            harness.reconstruct_prompt(harness.read_json(package_dir / "graph.json")),
            large_hash,
        )
        harness.write_json(package_dir / "manifest.json", manifest)

        result = harness.import_session(package_dir, workspace_dir)
        restored = workspace_dir / artifact["target_path"]

        assert restored.exists()
        assert restored.stat().st_size == len(large_payload)
        assert harness.file_sha256_and_size(restored) == (large_hash, len(large_payload))
        assert result["restore_report"][0]["size_bytes"] == len(large_payload)


def test_local_agent_graph_prompt_reconstruction_is_deterministic():
    harness = load_harness()
    session = harness.run_reference_session()
    prompt_a = harness.reconstruct_prompt_from_messages(session.messages)
    artifact_record = harness.build_artifact_record(session, harness.ArtifactExportPolicy())
    graph = harness.build_graph(session, artifact_record, prompt_a)
    prompt_b = harness.reconstruct_prompt(graph)

    assert prompt_a == prompt_b
    assert harness.canonical_graph_hash(graph) == graph["graph_hash"]
