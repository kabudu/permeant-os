#!/usr/bin/env python3
"""Agent Memory Graph conformance adapters for framework-style runtimes.

The adapters in this module are dependency-free reference mappings. They model
the state shapes PermeantOS expects from real integrations without importing
LangGraph, MCP servers, or browser runtimes in the test suite.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GRAPH_VERSION = "0.1"
CREATED_AT = "2026-06-20T00:00:00Z"
SCHEMA_ID = "https://www.permeantos.org/schemas/agent-memory-graph-v0.schema.json"


class AdapterConformanceError(ValueError):
    """Raised when an adapter conformance package cannot be verified."""


@dataclass(frozen=True)
class AdapterDefinition:
    adapter_id: str
    runtime: str
    runtime_family: str
    model: str
    description: str
    export_modes: tuple[str, ...]
    import_modes: tuple[str, ...]
    graph_features: tuple[str, ...]
    limitations: tuple[str, ...]


ADAPTERS: dict[str, AdapterDefinition] = {
    "langgraph_durable_state": AdapterDefinition(
        adapter_id="langgraph_durable_state",
        runtime="langgraph-style-durable-state",
        runtime_family="durable_state_graph",
        model="framework-managed",
        description="Maps thread state, checkpoints, tasks, and long-term stores to Agent Memory Graph v0.",
        export_modes=("snapshot", "checkpoint"),
        import_modes=("resume_from_checkpoint", "rebind_store"),
        graph_features=(
            "messages",
            "tasks",
            "checkpoints",
            "semantic_memories",
            "retrievals",
            "trace_spans",
        ),
        limitations=(
            "Dependency-free conformance mapping; it does not call LangGraph APIs.",
            "External stores are represented by stable references and must be rebound by a live adapter.",
        ),
    ),
    "mcp_resource_session": AdapterDefinition(
        adapter_id="mcp_resource_session",
        runtime="mcp-backed-tool-session",
        runtime_family="tool_resource_session",
        model="framework-managed",
        description="Maps MCP-style tool calls, tool results, resource links, and capability references to Agent Memory Graph v0.",
        export_modes=("snapshot", "capability_rebind"),
        import_modes=("resume_read_only_tools", "rebind_capabilities"),
        graph_features=(
            "messages",
            "tool_calls",
            "tool_results",
            "credential_refs",
            "artifacts",
            "trace_spans",
        ),
        limitations=(
            "Dependency-free conformance mapping; it does not connect to an MCP transport.",
            "Capabilities are represented as rebindable references and never include secret values.",
        ),
    ),
}


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def canonical_graph_hash(graph: dict[str, Any]) -> str:
    payload = copy.deepcopy(graph)
    payload.pop("graph_hash", None)
    return sha256_json(payload)


def provenance(adapter: AdapterDefinition) -> dict[str, str]:
    return {
        "runtime": adapter.runtime,
        "captured_at": CREATED_AT,
        "adapter": f"framework_adapters.py:{adapter.adapter_id}",
    }


def base_node(adapter: AdapterDefinition, node_id: str, node_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    node = {
        "id": node_id,
        "type": node_type,
        "created_at": CREATED_AT,
        "content_hash": sha256_json(payload),
        "provenance": provenance(adapter),
        **payload,
    }
    return node


def adapter_capability_manifest() -> dict[str, Any]:
    return {
        "manifest_version": "adapter-capabilities-v0",
        "schema": SCHEMA_ID,
        "created_at": CREATED_AT,
        "adapters": [
            {
                "adapter_id": adapter.adapter_id,
                "runtime": adapter.runtime,
                "runtime_family": adapter.runtime_family,
                "description": adapter.description,
                "export_modes": list(adapter.export_modes),
                "import_modes": list(adapter.import_modes),
                "graph_features": list(adapter.graph_features),
                "limitations": list(adapter.limitations),
            }
            for adapter in ADAPTERS.values()
        ],
    }


def compatibility_matrix() -> list[dict[str, Any]]:
    features = sorted({feature for adapter in ADAPTERS.values() for feature in adapter.graph_features})
    return [
        {
            "adapter_id": adapter.adapter_id,
            "runtime": adapter.runtime,
            "runtime_family": adapter.runtime_family,
            "features": {feature: feature in adapter.graph_features for feature in features},
            "export_modes": list(adapter.export_modes),
            "import_modes": list(adapter.import_modes),
        }
        for adapter in ADAPTERS.values()
    ]


def build_langgraph_style_graph(adapter: AdapterDefinition) -> dict[str, Any]:
    participants = [
        {"id": "agent:langgraph-reference", "kind": "agent", "name": "LangGraph style agent", "model": adapter.model},
        {"id": "user:operator", "kind": "user", "name": "Operator"},
        {"id": "runtime:langgraph-store", "kind": "runtime", "provider": "durable-state-graph"},
    ]
    nodes = [
        base_node(
            adapter,
            "event:langgraph-start",
            "event",
            {
                "actor_id": "runtime:langgraph-store",
                "event_kind": "runtime",
                "memory_scope": "thread",
                "memory_tier": "active_context",
                "sensitivity": "internal",
                "retention": "session",
                "redaction_state": "none",
                "extensions": {"org.permeantos.adapter.thread_id": "thread:lg-reference"},
            },
        ),
        base_node(
            adapter,
            "turn:user:langgraph-1",
            "message",
            {
                "actor_id": "user:operator",
                "role": "user",
                "content": "Continue the migration checklist from durable state.",
                "memory_scope": "thread",
                "memory_tier": "active_context",
                "sensitivity": "internal",
                "retention": "session",
                "redaction_state": "none",
            },
        ),
        base_node(
            adapter,
            "turn:assistant:langgraph-1",
            "message",
            {
                "actor_id": "agent:langgraph-reference",
                "role": "assistant",
                "content": "I will resume from the checkpoint and preserve the open task.",
                "memory_scope": "thread",
                "memory_tier": "active_context",
                "sensitivity": "internal",
                "retention": "session",
                "redaction_state": "none",
            },
        ),
        base_node(
            adapter,
            "task:langgraph-open-checklist",
            "task",
            {
                "actor_id": "agent:langgraph-reference",
                "memory_scope": "thread",
                "memory_tier": "working",
                "sensitivity": "internal",
                "retention": "durable",
                "redaction_state": "none",
                "status": "in_progress",
                "resume_policy": "retry_safe",
                "items": [
                    {"text": "Validate imported graph", "status": "completed"},
                    {"text": "Resume pending framework node", "status": "in_progress"},
                ],
            },
        ),
        base_node(
            adapter,
            "memory:langgraph-user-preference",
            "memory",
            {
                "actor_id": "agent:langgraph-reference",
                "memory_scope": "user",
                "memory_tier": "recall",
                "sensitivity": "internal",
                "retention": "durable",
                "redaction_state": "none",
                "memory_kind": "semantic",
                "quality_state": "verified",
                "historical_state": "current",
                "trust_level": "derived",
                "subject": "user",
                "predicate": "prefers",
                "object": "explicit validation before merge",
                "namespace": ["memories", "user"],
                "key": "merge-validation-preference",
                "text_hash": sha256_bytes(b"user prefers explicit validation before merge"),
                "embedding_model": "adapter-managed",
                "embedding_dim": 1,
                "embedding_hash": sha256_json([1.0]),
                "distance_metric": "unknown",
                "vector_store_ref": "store:langgraph:long-term-memory",
            },
        ),
        base_node(
            adapter,
            "retrieval:langgraph-memory",
            "retrieval",
            {
                "actor_id": "agent:langgraph-reference",
                "memory_scope": "thread",
                "memory_tier": "recall",
                "sensitivity": "internal",
                "retention": "session",
                "redaction_state": "none",
                "query_hash": sha256_bytes(b"merge validation preference"),
                "retrieval_kind": "hybrid",
                "planner_profile": "adapter_defined",
                "policy_profile": "assistant",
                "scorer_kind": "adapter_defined",
                "selected_channels": ["semantic", "metadata"],
                "candidate_sources": ["semantic_neighbor", "adapter_defined"],
                "planner_stages": ["load_thread_checkpoint", "query_long_term_store"],
                "graph_expansion_max_hops": 1,
                "historical_mode": "current_only",
                "results": [
                    {
                        "node_id": "memory:langgraph-user-preference",
                        "rank": 1,
                        "score": 1.0,
                        "score_kind": "adapter_defined",
                        "score_breakdown": [{"name": "semantic", "value": 1.0, "weight": 1.0}],
                        "candidate_source": "semantic_neighbor",
                    }
                ],
                "selection_policy": "framework_store_top_result",
            },
        ),
        base_node(
            adapter,
            "checkpoint:langgraph-thread",
            "checkpoint",
            {
                "actor_id": "runtime:langgraph-store",
                "memory_scope": "thread",
                "memory_tier": "external",
                "sensitivity": "internal",
                "retention": "durable",
                "redaction_state": "none",
                "checkpoint_kind": "workflow",
                "state_hash": sha256_bytes(b"langgraph-thread-state-v0"),
                "resume_ref": "checkpoint:langgraph:thread:lg-reference",
            },
        ),
        base_node(
            adapter,
            "trace:langgraph-node",
            "trace_span",
            {
                "actor_id": "runtime:langgraph-store",
                "memory_scope": "thread",
                "memory_tier": "working",
                "sensitivity": "internal",
                "retention": "session",
                "redaction_state": "none",
                "trace_id": "trace-langgraph-reference",
                "span_id": "span-node-resume",
                "span_kind": "orchestration",
                "started_at": CREATED_AT,
                "ended_at": CREATED_AT,
            },
        ),
    ]
    edges = [
        {"from": "event:langgraph-start", "to": "turn:user:langgraph-1", "type": "caused"},
        {"from": "turn:user:langgraph-1", "to": "turn:assistant:langgraph-1", "type": "caused"},
        {"from": "turn:assistant:langgraph-1", "to": "task:langgraph-open-checklist", "type": "produced"},
        {"from": "retrieval:langgraph-memory", "to": "memory:langgraph-user-preference", "type": "retrieved"},
        {"from": "checkpoint:langgraph-thread", "to": "task:langgraph-open-checklist", "type": "checkpointed"},
        {"from": "trace:langgraph-node", "to": "checkpoint:langgraph-thread", "type": "references"},
    ]
    return build_graph_envelope(adapter, "graph:langgraph-reference:0001", "agent:langgraph-reference", participants, nodes, edges)


def build_mcp_resource_session_graph(adapter: AdapterDefinition) -> dict[str, Any]:
    participants = [
        {"id": "agent:mcp-reference", "kind": "agent", "name": "MCP style agent", "model": adapter.model},
        {"id": "user:operator", "kind": "user", "name": "Operator"},
        {"id": "tool:mcp-files", "kind": "tool", "provider": "mcp.filesystem"},
        {"id": "runtime:mcp-session", "kind": "runtime", "provider": "mcp"},
    ]
    nodes = [
        base_node(
            adapter,
            "turn:user:mcp-1",
            "message",
            {
                "actor_id": "user:operator",
                "role": "user",
                "content": "List the project manifest through the MCP resource server.",
                "memory_scope": "thread",
                "memory_tier": "active_context",
                "sensitivity": "internal",
                "retention": "session",
                "redaction_state": "none",
            },
        ),
        base_node(
            adapter,
            "tool:call:mcp-list",
            "tool_call",
            {
                "actor_id": "agent:mcp-reference",
                "memory_scope": "thread",
                "memory_tier": "working",
                "sensitivity": "internal",
                "retention": "session",
                "redaction_state": "none",
                "name": "resources/read",
                "provider": "mcp.filesystem",
                "call_id": "call:mcp:list-project-manifest",
                "arguments_hash": sha256_json({"uri": "file://workspace/Cargo.toml"}),
                "input_schema_hash": sha256_json({"uri": "string"}),
                "side_effect": "read_only",
                "status": "completed",
                "resume_policy": "never_retry",
                "approval_state": "not_required",
            },
        ),
        base_node(
            adapter,
            "tool:result:mcp-list",
            "tool_result",
            {
                "actor_id": "tool:mcp-files",
                "memory_scope": "thread",
                "memory_tier": "working",
                "sensitivity": "internal",
                "retention": "session",
                "redaction_state": "none",
                "status": "completed",
                "result_hash": sha256_bytes(b"workspace Cargo manifest resource metadata"),
                "output_schema_hash": sha256_json({"contents": "array"}),
                "is_error": False,
                "resource_refs": ["file://workspace/Cargo.toml"],
            },
        ),
        base_node(
            adapter,
            "artifact:mcp-cargo-manifest",
            "artifact",
            {
                "actor_id": "tool:mcp-files",
                "memory_scope": "thread",
                "memory_tier": "external",
                "sensitivity": "internal",
                "retention": "session",
                "redaction_state": "external_only",
                "artifact_kind": "external",
                "path": "Cargo.toml",
                "uri": "file://workspace/Cargo.toml",
                "content_ref": "mcp-resource:file://workspace/Cargo.toml",
                "root_ref": "workspace",
                "restore_policy": "external_rebind",
            },
        ),
        base_node(
            adapter,
            "credential:mcp-filesystem",
            "credential_ref",
            {
                "actor_id": "runtime:mcp-session",
                "memory_scope": "external",
                "memory_tier": "external",
                "sensitivity": "secret",
                "retention": "delete_on_import",
                "redaction_state": "external_only",
                "capability": "mcp.filesystem.read",
                "binding": "target must authorize workspace filesystem read resource",
                "required": True,
            },
        ),
        base_node(
            adapter,
            "checkpoint:mcp-session",
            "checkpoint",
            {
                "actor_id": "runtime:mcp-session",
                "memory_scope": "thread",
                "memory_tier": "external",
                "sensitivity": "internal",
                "retention": "session",
                "redaction_state": "external_only",
                "checkpoint_kind": "session",
                "state_hash": sha256_bytes(b"mcp-session-resource-state-v0"),
                "resume_ref": "mcp-session:reference",
            },
        ),
        base_node(
            adapter,
            "trace:mcp-tool-call",
            "trace_span",
            {
                "actor_id": "runtime:mcp-session",
                "memory_scope": "thread",
                "memory_tier": "working",
                "sensitivity": "internal",
                "retention": "session",
                "redaction_state": "none",
                "trace_id": "trace-mcp-reference",
                "span_id": "span-tool-call",
                "span_kind": "tool",
                "started_at": CREATED_AT,
                "ended_at": CREATED_AT,
            },
        ),
    ]
    edges = [
        {"from": "turn:user:mcp-1", "to": "tool:call:mcp-list", "type": "caused"},
        {"from": "tool:call:mcp-list", "to": "tool:result:mcp-list", "type": "produced"},
        {"from": "tool:result:mcp-list", "to": "artifact:mcp-cargo-manifest", "type": "produced"},
        {"from": "credential:mcp-filesystem", "to": "tool:call:mcp-list", "type": "approves"},
        {"from": "checkpoint:mcp-session", "to": "tool:call:mcp-list", "type": "checkpointed"},
        {"from": "trace:mcp-tool-call", "to": "tool:call:mcp-list", "type": "references"},
    ]
    return build_graph_envelope(adapter, "graph:mcp-resource-session:0001", "agent:mcp-reference", participants, nodes, edges)


def build_graph_envelope(
    adapter: AdapterDefinition,
    graph_id: str,
    agent_id: str,
    participants: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    graph = {
        "graph_id": graph_id,
        "graph_version": GRAPH_VERSION,
        "created_at": CREATED_AT,
        "agent": {
            "id": agent_id,
            "runtime": adapter.runtime,
            "model": adapter.model,
            "extensions": {"org.permeantos.adapter.id": adapter.adapter_id},
        },
        "participants": participants,
        "policies": {
            "redaction_policy": "required",
            "retention_policy": "durable",
            "required_approval_for_side_effects": True,
            "default_replay_policy": "ask_user",
            "extensions": {
                "org.permeantos.adapter.credential_policy": "rebind_on_import",
                "org.permeantos.adapter.artifact_policy": "rebind_external_artifacts",
            },
        },
        "nodes": nodes,
        "edges": edges,
        "kv_spans": [],
        "extensions": {
            "org.permeantos.adapter.id": adapter.adapter_id,
            "org.permeantos.adapter.runtime_family": adapter.runtime_family,
        },
    }
    graph["graph_hash"] = canonical_graph_hash(graph)
    return graph


def build_graph(adapter_id: str) -> dict[str, Any]:
    adapter = ADAPTERS.get(adapter_id)
    if adapter is None:
        raise AdapterConformanceError(f"unknown adapter: {adapter_id}")
    if adapter_id == "langgraph_durable_state":
        return build_langgraph_style_graph(adapter)
    if adapter_id == "mcp_resource_session":
        return build_mcp_resource_session_graph(adapter)
    raise AdapterConformanceError(f"adapter has no graph builder: {adapter_id}")


def validate_graph_conformance(graph: dict[str, Any], adapter_manifest: dict[str, Any]) -> None:
    if graph.get("graph_hash") != canonical_graph_hash(graph):
        raise AdapterConformanceError("graph hash mismatch")

    adapter_id = graph.get("extensions", {}).get("org.permeantos.adapter.id")
    adapters = {entry["adapter_id"]: entry for entry in adapter_manifest.get("adapters", [])}
    adapter_entry = adapters.get(adapter_id)
    if adapter_entry is None:
        raise AdapterConformanceError(f"adapter manifest is missing adapter: {adapter_id}")
    if graph.get("agent", {}).get("runtime") != adapter_entry.get("runtime"):
        raise AdapterConformanceError("graph runtime does not match adapter manifest")

    node_ids = {node["id"] for node in graph.get("nodes", [])}
    participant_ids = {participant["id"] for participant in graph.get("participants", [])}
    if graph.get("agent", {}).get("id") not in participant_ids:
        raise AdapterConformanceError("agent participant is missing")
    for node in graph.get("nodes", []):
        actor_id = node.get("actor_id")
        if actor_id and actor_id not in participant_ids:
            raise AdapterConformanceError(f"node {node['id']} references unknown actor {actor_id}")
    for edge in graph.get("edges", []):
        if edge["from"] not in node_ids or edge["to"] not in node_ids:
            raise AdapterConformanceError(f"edge references unknown node: {edge['from']} -> {edge['to']}")


def export_adapter_package(adapter_id: str, package_dir: Path) -> dict[str, Any]:
    graph = build_graph(adapter_id)
    manifest = adapter_capability_manifest()
    write_json(package_dir / "graph.json", graph)
    write_json(package_dir / "adapter-manifest.json", manifest)
    return {"graph": graph, "adapter_manifest": manifest}


def export_all_conformance_packages(root_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        adapter_id: export_adapter_package(adapter_id, root_dir / adapter_id)
        for adapter_id in ADAPTERS
    }


def import_adapter_package(package_dir: Path) -> dict[str, Any]:
    graph = read_json(package_dir / "graph.json")
    manifest = read_json(package_dir / "adapter-manifest.json")
    validate_graph_conformance(graph, manifest)
    adapter_id = graph["extensions"]["org.permeantos.adapter.id"]
    return {
        "status": "verified",
        "adapter_id": adapter_id,
        "runtime": graph["agent"]["runtime"],
        "graph_hash": graph["graph_hash"],
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("manifest")
    subcommands.add_parser("matrix")

    export_parser = subcommands.add_parser("export")
    export_parser.add_argument("adapter_id", choices=sorted(ADAPTERS))
    export_parser.add_argument("package_dir", type=Path)

    import_parser = subcommands.add_parser("import")
    import_parser.add_argument("package_dir", type=Path)

    args = parser.parse_args()
    if args.command == "manifest":
        print(json.dumps(adapter_capability_manifest(), indent=2, sort_keys=True))
    elif args.command == "matrix":
        print(json.dumps(compatibility_matrix(), indent=2, sort_keys=True))
    elif args.command == "export":
        export_adapter_package(args.adapter_id, args.package_dir)
    elif args.command == "import":
        print(json.dumps(import_adapter_package(args.package_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
