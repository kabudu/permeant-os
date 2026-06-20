import copy
import importlib.util
import json
import pathlib
import sys
import tempfile

import jsonschema


ROOT = pathlib.Path(__file__).resolve().parents[1]
ADAPTERS_PATH = ROOT / "examples" / "agent-memory-graph" / "framework_adapters.py"
SCHEMA_PATH = ROOT / "docs" / "schemas" / "agent-memory-graph-v0.schema.json"


def load_adapters():
    spec = importlib.util.spec_from_file_location("framework_adapters", ADAPTERS_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_schema():
    return json.loads(SCHEMA_PATH.read_text())


def test_adapter_capability_manifest_covers_two_independent_runtimes():
    adapters = load_adapters()

    manifest = adapters.adapter_capability_manifest()
    entries = manifest["adapters"]

    assert manifest["manifest_version"] == "adapter-capabilities-v0"
    assert {entry["adapter_id"] for entry in entries} == {
        "langgraph_durable_state",
        "mcp_resource_session",
    }
    assert len({entry["runtime_family"] for entry in entries}) == 2
    for entry in entries:
        assert entry["export_modes"]
        assert entry["import_modes"]
        assert entry["graph_features"]
        assert entry["limitations"]


def test_framework_adapter_graphs_validate_against_agent_memory_graph_schema():
    adapters = load_adapters()
    schema = load_schema()
    validator = jsonschema.Draft202012Validator(schema)

    for adapter_id in adapters.ADAPTERS:
        graph = adapters.build_graph(adapter_id)
        validator.validate(graph)
        adapters.validate_graph_conformance(graph, adapters.adapter_capability_manifest())

        assert graph["graph_hash"] == adapters.canonical_graph_hash(graph)
        assert graph["agent"]["extensions"]["org.permeantos.adapter.id"] == adapter_id
        assert graph["extensions"]["org.permeantos.adapter.id"] == adapter_id
        assert graph["kv_spans"] == []


def test_framework_adapter_export_import_conformance_roundtrip():
    adapters = load_adapters()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        packages = adapters.export_all_conformance_packages(root)

        assert set(packages) == set(adapters.ADAPTERS)
        for adapter_id in adapters.ADAPTERS:
            result = adapters.import_adapter_package(root / adapter_id)

            assert result["status"] == "verified"
            assert result["adapter_id"] == adapter_id
            assert result["runtime"] == adapters.ADAPTERS[adapter_id].runtime
            assert result["node_count"] > 0
            assert result["edge_count"] > 0


def test_framework_adapter_import_rejects_graph_hash_mismatch():
    adapters = load_adapters()

    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        adapters.export_adapter_package("langgraph_durable_state", package_dir)
        graph_path = package_dir / "graph.json"
        graph = json.loads(graph_path.read_text())
        graph["nodes"][0]["extensions"]["org.permeantos.adapter.thread_id"] = "thread:tampered"
        graph_path.write_text(json.dumps(graph, indent=2, sort_keys=True) + "\n")

        try:
            adapters.import_adapter_package(package_dir)
        except adapters.AdapterConformanceError as exc:
            assert "graph hash mismatch" in str(exc)
        else:
            raise AssertionError("graph hash mismatch should have failed")


def test_framework_adapter_import_rejects_manifest_runtime_mismatch():
    adapters = load_adapters()

    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        adapters.export_adapter_package("mcp_resource_session", package_dir)
        manifest_path = package_dir / "adapter-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["adapters"][1]["runtime"] = "wrong-runtime"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

        try:
            adapters.import_adapter_package(package_dir)
        except adapters.AdapterConformanceError as exc:
            assert "graph runtime does not match adapter manifest" in str(exc)
        else:
            raise AssertionError("runtime mismatch should have failed")


def test_framework_adapter_import_rejects_unknown_edge_target():
    adapters = load_adapters()

    with tempfile.TemporaryDirectory() as temp_dir:
        package_dir = pathlib.Path(temp_dir) / "package"
        package = adapters.export_adapter_package("langgraph_durable_state", package_dir)
        graph = copy.deepcopy(package["graph"])
        graph["edges"][0]["to"] = "message:missing"
        graph["graph_hash"] = adapters.canonical_graph_hash(graph)
        adapters.write_json(package_dir / "graph.json", graph)

        try:
            adapters.import_adapter_package(package_dir)
        except adapters.AdapterConformanceError as exc:
            assert "edge references unknown node" in str(exc)
        else:
            raise AssertionError("unknown edge target should have failed")
