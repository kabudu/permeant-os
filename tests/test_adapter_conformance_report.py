from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run-adapter-conformance.py"


def test_adapter_conformance_report_exports_and_imports_reference_packages():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = pathlib.Path(tmpdir) / "adapter-conformance"
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--out-dir", str(out_dir)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr + result.stdout
        report = json.loads((out_dir / "adapter-conformance-report.json").read_text())
        assert report["schema_version"] == "permeantos-adapter-conformance-v0"
        assert report["ok"] is True
        assert set(report["framework_adapter_ids"]) == {"langgraph_durable_state", "mcp_resource_session"}
        assert (out_dir / "framework-adapter-manifest.json").is_file()
        assert (out_dir / "framework-adapter-matrix.json").is_file()
        for adapter in report["exported_adapters"]:
            assert adapter["export_ok"] is True
            assert adapter["import_ok"] is True
            export_dir = out_dir / adapter["export_dir"]
            assert (export_dir / "graph.json").is_file()
            assert (export_dir / "adapter-manifest.json").is_file()


def test_adapter_conformance_schema_is_documented_and_used_by_evidence_job():
    policy = (ROOT / "docs" / "versioning-policy.md").read_text()
    evidence_runner = (ROOT / "scripts" / "run-evidence-job.py").read_text()

    assert "permeantos-adapter-conformance-v0" in policy
    assert "run-adapter-conformance.py" in evidence_runner
