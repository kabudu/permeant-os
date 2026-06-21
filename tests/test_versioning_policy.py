from __future__ import annotations

import json
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "docs" / "versioning-policy.md"
GRAPH_SCHEMA_PATH = ROOT / "docs" / "schemas" / "agent-memory-graph-v0.schema.json"

EXPECTED_USXF_VERSION = "1.1"
EXPECTED_GRAPH_SCHEMA_ID = "https://www.permeantos.org/schemas/agent-memory-graph-v0.schema.json"
EXPECTED_GRAPH_VERSION = "0.1"
EXPECTED_TOOL_SCHEMAS = {
    "scripts/summarize-benchmark-manifests.py": "permeantos-benchmark-summary-v0",
    "scripts/analyze-fidelity-horizons.py": "permeantos-fidelity-horizon-suite-v0",
    "scripts/plan-context-benchmarks.py": "permeantos-context-benchmark-matrix-v0",
    "scripts/compare-transfer-quantization.py": "permeantos-transfer-quantization-comparison-v0",
    "scripts/plan-transfer-codecs.py": "permeantos-transfer-codec-plan-v0",
    "scripts/aws-real-runtime-e2e.sh": "permeantos-aws-e2e-preflight-v0",
    "scripts/generate-evidence-index.py": "permeantos-evidence-index-v0",
}


def test_python_sdk_exports_current_public_versions():
    sys.path.insert(0, str(ROOT / "sdk" / "python"))
    try:
        import permeantos

        assert permeantos.USXF_VERSION == EXPECTED_USXF_VERSION
        assert permeantos.AGENT_MEMORY_GRAPH_SCHEMA_ID == EXPECTED_GRAPH_SCHEMA_ID
        assert permeantos.AGENT_MEMORY_GRAPH_GRAPH_VERSION == EXPECTED_GRAPH_VERSION
    finally:
        sys.path.remove(str(ROOT / "sdk" / "python"))


def test_agent_memory_graph_schema_identifier_matches_policy():
    schema = json.loads(GRAPH_SCHEMA_PATH.read_text())
    policy = POLICY_PATH.read_text()

    assert schema["$id"] == EXPECTED_GRAPH_SCHEMA_ID
    assert schema["properties"]["graph_version"]["const"] == EXPECTED_GRAPH_VERSION
    assert EXPECTED_GRAPH_SCHEMA_ID in policy
    assert f"current graph payload version is `{EXPECTED_GRAPH_VERSION}`" in policy


def test_rust_usxf_constants_match_policy():
    constants = (ROOT / "crates" / "usxf-core" / "src" / "version.rs").read_text()
    policy = POLICY_PATH.read_text()

    assert f'pub const USXF_VERSION: &str = "{EXPECTED_USXF_VERSION}";' in constants
    assert f'pub const AGENT_MEMORY_GRAPH_GRAPH_VERSION: &str = "{EXPECTED_GRAPH_VERSION}";' in constants
    assert EXPECTED_USXF_VERSION in policy
    assert EXPECTED_GRAPH_SCHEMA_ID in constants


def test_tool_schema_versions_are_documented_and_emitted():
    policy = POLICY_PATH.read_text()

    for relative_path, expected_schema in EXPECTED_TOOL_SCHEMAS.items():
        source = (ROOT / relative_path).read_text()
        assert expected_schema in source
        assert expected_schema in policy


def test_release_tag_policy_matches_current_tag_shape():
    policy = POLICY_PATH.read_text()
    pattern = re.compile(r"^v<major>\.<minor>\.<patch>-<roadmap-slug>$", re.MULTILINE)

    assert pattern.search(policy)
