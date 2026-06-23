from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-publishing-policy.py"


def test_publishing_policy_report_keeps_real_publishing_disabled():
    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = pathlib.Path(tmpdir) / "publishing-policy.json"
        result = subprocess.run(
            [sys.executable, str(CHECKER), "--json-out", str(report_path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr + result.stdout
        report = json.loads(report_path.read_text())
        assert report["schema_version"] == "permeantos-publishing-policy-v0"
        assert report["ok"] is True
        assert report["mode"] == "pre-publication"
        assert report["publishing_enabled"] is False
        checks = {check["name"]: check for check in report["checks"]}
        assert checks["workflow-forbids:cargo publish"]["ok"] is True
        assert checks["workflow-forbids:twine upload"]["ok"] is True
        assert checks["workflow-forbids:gh release create"]["ok"] is True
        assert checks["real-release-workflow-guarded"]["ok"] is True
        assert checks["python-publish-disabled:permeantos"]["ok"] is True
        crate_checks = [name for name in checks if name.startswith("crate-publish-disabled:")]
        assert crate_checks
        assert all(checks[name]["ok"] for name in crate_checks)


def test_publishing_policy_is_wired_into_pr_ci_and_docs_index():
    workflow = (ROOT / ".github" / "workflows" / "pr-ci.yml").read_text()
    docs_index = (ROOT / "docs" / "index.md").read_text()
    versioning = (ROOT / "docs" / "versioning-policy.md").read_text()

    assert "scripts/check-publishing-policy.py --json-out /tmp/permeantos-publishing-policy.json" in workflow
    assert "publishing-policy.md" in docs_index
    assert "permeantos-publishing-policy-v0" in versioning
