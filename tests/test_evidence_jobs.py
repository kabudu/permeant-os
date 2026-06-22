from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "evidence-jobs.yml"
RUNNER = ROOT / "scripts" / "run-evidence-job.py"


def test_evidence_workflow_has_safe_scheduled_non_provisioning_lane():
    workflow = WORKFLOW.read_text()
    runner = RUNNER.read_text()

    assert "schedule:" in workflow
    assert "scripts/run-evidence-job.py \\" in workflow
    assert "--mode non-provisioning" in workflow
    assert "ubuntu-latest" in workflow
    assert "permeantos-non-provisioning-evidence" in workflow
    assert "PERMEANT_EVIDENCE_INCLUDE_STARTER_DEMO: \"1\"" in workflow
    assert "rustup toolchain install stable --profile minimal" in workflow
    assert '"tests/test_runtime_http_bridge.py"' in runner
    assert "starter-migration-demo" in runner
    assert "starter-demo" in runner
    assert "run-adapter-conformance.py" in runner
    assert "check-publishing-policy.py" in runner
    assert 'PERMEANT_EVIDENCE_INCLUDE_SOCKET_TESTS", "1"' in runner


def test_evidence_workflow_requires_manual_confirmation_for_aws_lane():
    workflow = WORKFLOW.read_text()

    assert "mode == 'aws-real-runtime'" in workflow
    assert "confirm_aws_cost == 'RUN_AWS_REAL_RUNTIME'" in workflow
    assert "confirm_aws_cost != 'RUN_AWS_REAL_RUNTIME'" in workflow
    assert "environment: aws-real-runtime-evidence" in workflow
    assert "permeantos-aws-evidence" in workflow
    assert "--confirm RUN_AWS_REAL_RUNTIME" in workflow


def test_evidence_runner_rejects_unconfirmed_aws_mode_without_side_effects():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = pathlib.Path(tmpdir) / "evidence"
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--mode", "aws-real-runtime", "--out-dir", str(out_dir)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode != 0
        assert "requires --confirm RUN_AWS_REAL_RUNTIME" in result.stderr
        assert not (out_dir / "evidence-job-report.json").exists()


def test_non_provisioning_evidence_job_emits_report_and_skips_cloud():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = pathlib.Path(tmpdir) / "evidence"
        env = {
            **os.environ,
            "PERMEANT_EVIDENCE_INCLUDE_SOCKET_TESTS": "0",
            "PERMEANT_EVIDENCE_INCLUDE_STARTER_DEMO": "0",
        }
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--mode", "non-provisioning", "--out-dir", str(out_dir)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr + result.stdout
        report = json.loads((out_dir / "evidence-job-report.json").read_text())
        assert report["schema_version"] == "permeantos-evidence-job-v0"
        assert report["mode"] == "non-provisioning"
        assert report["ok"] is True
        assert report["cloud_resources_created"] is False
        assert report["cleanup_required"] is False
        assert report["socket_tests_included"] is False
        assert report["starter_demo_included"] is False
        step_names = {step["name"] for step in report["steps"]}
        assert {
            "adapter-and-evidence-tests",
            "adapter-conformance-report",
            "generate-evidence-index",
            "plan-model-runtime-validations",
            "aws-preflight-non-provisioning",
            "package-readiness",
            "publishing-policy",
        } == step_names
        assert (out_dir / "adapter-conformance" / "adapter-conformance-report.json").is_file()
        assert (out_dir / "publishing-policy.json").is_file()
        preflight_state = out_dir / "aws-preflight-state" / "latest"
        preflight_report = json.loads((preflight_state / "preflight-report.json").read_text())
        checks = {check["name"]: check["status"] for check in preflight_report["checks"]}
        assert checks["aws:identity"] == "skip"
        assert checks["local:permeant_cli"] == "skip"
        assert checks["source:continuation_file"] == "skip"
