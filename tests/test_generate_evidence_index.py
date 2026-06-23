from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate-evidence-index.py"
INDEX_JSON = ROOT / "docs" / "evidence-index.json"
INDEX_MD = ROOT / "docs" / "evidence-index.md"


def run_generator(*args: str):
    return subprocess.run(
        [str(GENERATOR), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_generator_emits_public_evidence_index_json():
    result = run_generator()

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "permeantos-evidence-index-v0"
    assert payload["record_count"] == len(payload["records"])
    assert payload["record_count"] >= 7
    record_ids = {record["id"] for record in payload["records"]}
    assert "qwen25-mlx-vllm-aws-long-horizon-roundtrip" in record_ids
    assert "tinyllama-mlx-vllm-aws-raw-structural" in record_ids
    assert "qwen25-mlx-llamacpp-canonical-kv-feed" in record_ids
    assert "agent-memory-graph-v0-schema" in record_ids


def test_records_have_existing_reports_and_explicit_limitations():
    payload = json.loads(run_generator().stdout)

    for record in payload["records"]:
        assert record["proof_reports"], record["id"]
        assert record["limitations"], record["id"]
        for relative_path in record["proof_reports"]:
            assert (ROOT / relative_path).is_file(), f"{record['id']} missing {relative_path}"


def test_generated_evidence_index_files_are_current():
    with tempfile.TemporaryDirectory() as tmpdir:
        json_out = pathlib.Path(tmpdir) / "evidence-index.json"
        md_out = pathlib.Path(tmpdir) / "evidence-index.md"
        result = run_generator("--json-out", str(json_out), "--markdown-out", str(md_out))

        assert result.returncode == 0, result.stderr
        assert json.loads(json_out.read_text()) == json.loads(INDEX_JSON.read_text())
        assert md_out.read_text() == INDEX_MD.read_text()
