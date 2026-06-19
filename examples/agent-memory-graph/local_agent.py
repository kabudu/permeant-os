#!/usr/bin/env python3
"""Minimal local Agent Memory Graph export/import harness.

This example is intentionally small and deterministic. It demonstrates graph-only
migration before live KV-cache attachment:

- run a fixed local agent session
- write one artifact through a simulated tool call
- export Agent Memory Graph JSON, artifact blobs, and a manifest
- import the package, verify hashes, reconstruct the prompt, and continue
  deterministically
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GRAPH_VERSION = "0.1"
CREATED_AT = "2026-06-19T00:00:00Z"
AGENT_ID = "agent:local-reference"
USER_ID = "user:local-reference"
TOOL_ID = "tool:local-fs"
MODEL_ID = "deterministic-local-agent-v0"
RUNTIME_ID = "examples/agent-memory-graph"
TOKENIZER_HASH = "sha256:" + hashlib.sha256(b"permeant-local-byte-tokenizer-v0").hexdigest()


class ImportVerificationError(ValueError):
    """Raised when an exported graph package cannot be verified."""


@dataclass(frozen=True)
class LocalSession:
    messages: list[dict[str, str]]
    artifact_path: str
    artifact_bytes: bytes
    deterministic_response: str


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def canonical_graph_hash(graph: dict[str, Any]) -> str:
    payload = copy.deepcopy(graph)
    payload.pop("graph_hash", None)
    return sha256_json(payload)


def tokenize_prompt(prompt: str) -> list[int]:
    """Stable byte-level tokenizer for the local reference harness."""
    return list(prompt.encode("utf-8"))


def token_hash(token_ids: list[int]) -> str:
    hasher = hashlib.sha256()
    for token_id in token_ids:
        hasher.update(int(token_id).to_bytes(2, byteorder="big"))
    return "sha256:" + hasher.hexdigest()


def simulated_kv_hash(token_ids: list[int]) -> str:
    hasher = hashlib.sha256()
    hasher.update(b"permeant-local-kv-v0\0")
    for position, token_id in enumerate(token_ids):
        hasher.update(position.to_bytes(4, byteorder="big"))
        hasher.update(int(token_id).to_bytes(2, byteorder="big"))
    return "sha256:" + hasher.hexdigest()


def deterministic_continue(prompt: str, artifact_hash: str) -> str:
    digest = hashlib.sha256(f"{prompt}\n{artifact_hash}".encode("utf-8")).hexdigest()
    return f"Deterministic continuation: report verified with digest {digest[:16]}."


def run_reference_session() -> LocalSession:
    artifact_path = "reports/result.json"
    artifact_payload = {
        "status": "complete",
        "title": "Agent Memory Graph local export",
        "findings": [
            "conversation state is reconstructable",
            "tool output artifacts are content-addressed",
            "continuation is deterministic after import",
        ],
    }
    artifact_bytes = (json.dumps(artifact_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    artifact_hash = sha256_bytes(artifact_bytes)
    messages = [
        {"role": "system", "content": "You are the PermeantOS local reference agent."},
        {"role": "user", "content": "Create a short migration report and remember its artifact."},
        {"role": "assistant", "content": "I will write a deterministic report artifact."},
        {"role": "tool", "content": f"fs.write_file wrote {artifact_path} with {artifact_hash}."},
        {"role": "assistant", "content": "The report artifact is complete and ready for migration."},
    ]
    prompt = reconstruct_prompt_from_messages(messages)
    response = deterministic_continue(prompt, artifact_hash)
    return LocalSession(
        messages=messages,
        artifact_path=artifact_path,
        artifact_bytes=artifact_bytes,
        deterministic_response=response,
    )


def reconstruct_prompt_from_messages(messages: list[dict[str, str]]) -> str:
    lines = []
    for message in messages:
        lines.append(f"<{message['role']}>")
        lines.append(message["content"])
        lines.append(f"</{message['role']}>")
    return "\n".join(lines) + "\n"


def reconstruct_prompt(graph: dict[str, Any]) -> str:
    messages = [
        {"role": node["role"], "content": node["content"]}
        for node in graph["nodes"]
        if node.get("type") == "message"
    ]
    return reconstruct_prompt_from_messages(messages)


def provenance() -> dict[str, str]:
    return {"runtime": RUNTIME_ID, "captured_at": CREATED_AT, "adapter": "local_agent.py"}


def base_node(node_id: str, node_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    node = {
        "id": node_id,
        "type": node_type,
        "created_at": CREATED_AT,
        "content_hash": sha256_json(payload),
        "provenance": provenance(),
        **payload,
    }
    return node


def build_graph(session: LocalSession, artifact_hash: str, prompt: str) -> dict[str, Any]:
    prompt_tokens = tokenize_prompt(prompt)
    nodes: list[dict[str, Any]] = [
        base_node(
            "event:start:local",
            "event",
            {
                "actor_id": USER_ID,
                "event_kind": "user_input",
                "memory_scope": "thread",
                "memory_tier": "active_context",
                "sensitivity": "internal",
                "retention": "session",
                "redaction_state": "none",
            },
        )
    ]

    message_ids = []
    for index, message in enumerate(session.messages, start=1):
        node_id = f"turn:{message['role']}:{index}"
        message_ids.append(node_id)
        actor_id = USER_ID if message["role"] == "user" else AGENT_ID
        if message["role"] == "tool":
            actor_id = TOOL_ID
        nodes.append(
            base_node(
                node_id,
                "message",
                {
                    "actor_id": actor_id,
                    "memory_scope": "thread",
                    "memory_tier": "active_context",
                    "sensitivity": "internal",
                    "retention": "session",
                    "redaction_state": "none",
                    "role": message["role"],
                    "content": message["content"],
                },
            )
        )

    nodes.extend(
        [
            base_node(
                "tool:call:write-report",
                "tool_call",
                {
                    "actor_id": AGENT_ID,
                    "memory_scope": "thread",
                    "memory_tier": "working",
                    "sensitivity": "internal",
                    "retention": "durable",
                    "redaction_state": "none",
                    "name": "fs.write_file",
                    "provider": "local-reference",
                    "call_id": "call:write-report",
                    "arguments_hash": sha256_json({"path": session.artifact_path, "content_sha256": artifact_hash}),
                    "input_schema_hash": sha256_json({"path": "string", "content": "string"}),
                    "idempotency_key": "local-reference-write-report",
                    "side_effect": "external_write",
                    "status": "completed",
                    "resume_policy": "never_retry",
                    "approval_state": "approved",
                    "external_resource_ids": [f"file:{session.artifact_path}"],
                },
            ),
            base_node(
                "tool:result:write-report",
                "tool_result",
                {
                    "actor_id": TOOL_ID,
                    "memory_scope": "thread",
                    "memory_tier": "working",
                    "sensitivity": "internal",
                    "retention": "durable",
                    "redaction_state": "none",
                    "result_hash": sha256_json({"path": session.artifact_path, "sha256": artifact_hash}),
                    "output_schema_hash": sha256_json({"path": "string", "sha256": "string"}),
                    "is_error": False,
                    "resource_refs": [f"artifact:{session.artifact_path}"],
                    "status": "completed",
                },
            ),
            base_node(
                "artifact:report",
                "artifact",
                {
                    "actor_id": TOOL_ID,
                    "memory_scope": "thread",
                    "memory_tier": "archival",
                    "sensitivity": "internal",
                    "retention": "durable",
                    "redaction_state": "none",
                    "artifact_kind": "file",
                    "path": session.artifact_path,
                    "uri": f"artifact://local/{session.artifact_path}",
                    "sha256": artifact_hash.removeprefix("sha256:"),
                    "size_bytes": len(session.artifact_bytes),
                    "media_type": "application/json",
                    "root_ref": "artifact-root:local-export",
                    "restore_policy": "required",
                },
            ),
            base_node(
                "memory:report-fact",
                "memory",
                {
                    "actor_id": AGENT_ID,
                    "memory_scope": "thread",
                    "memory_tier": "recall",
                    "sensitivity": "internal",
                    "retention": "durable",
                    "redaction_state": "none",
                    "quality_state": "verified",
                    "historical_state": "current",
                    "trust_level": "derived",
                    "valid_at": CREATED_AT,
                    "confidence": 1.0,
                    "memory_kind": "semantic",
                    "text_hash": sha256_bytes(b"report artifact is complete"),
                    "subject": "artifact:report",
                    "predicate": "status",
                    "object": "complete",
                    "namespace": ["local-reference", "facts"],
                    "key": "report-status",
                    "embedding_model": "deterministic-local-byte-tokenizer-v0",
                    "embedding_dim": 32,
                    "embedding_hash": sha256_bytes(b"report artifact is complete embedding"),
                    "distance_metric": "cosine",
                    "episode": {
                        "schema_version": "local-reference-v0",
                        "episode_id": "episode:local-export",
                        "continuity_state": "open",
                        "actor_ids": [AGENT_ID, USER_ID],
                        "started_at": CREATED_AT,
                        "boundary_labels": ["task", "session"],
                        "causal_record_ids": ["tool:call:write-report"],
                        "related_record_ids": ["artifact:report"],
                        "salience": {"reuse": 0.5, "novelty": 0.5, "unresolved": 0.1},
                    },
                    "conflict": {"review_state": "none", "conflicting_node_ids": [], "drift_score": 0.0},
                    "lineage_links": [{"node_id": "tool:result:write-report", "relation": "derived_from"}],
                },
            ),
            base_node(
                "checkpoint:prompt",
                "checkpoint",
                {
                    "actor_id": AGENT_ID,
                    "memory_scope": "thread",
                    "memory_tier": "external",
                    "sensitivity": "internal",
                    "retention": "durable",
                    "redaction_state": "none",
                    "checkpoint_kind": "session",
                    "state_hash": sha256_bytes(prompt.encode("utf-8")),
                    "resume_ref": "local-reference-session",
                },
            ),
            base_node(
                "kv:span:prompt",
                "kv_span",
                {
                    "actor_id": AGENT_ID,
                    "memory_scope": "thread",
                    "memory_tier": "active_context",
                    "sensitivity": "internal",
                    "retention": "session",
                    "redaction_state": "none",
                    "token_start": 0,
                    "token_end": len(prompt_tokens),
                    "cache_ref": "kv:simulated:prompt",
                    "tokenizer_hash": TOKENIZER_HASH,
                    "block_hashes": [token_hash(prompt_tokens)],
                },
            ),
        ]
    )

    edges = []
    previous = "event:start:local"
    for node_id in message_ids:
        edges.append({"from": previous, "to": node_id, "type": "caused"})
        previous = node_id
    edges.extend(
        [
            {"from": "turn:assistant:3", "to": "tool:call:write-report", "type": "caused"},
            {"from": "tool:call:write-report", "to": "tool:result:write-report", "type": "produced"},
            {"from": "tool:call:write-report", "to": "artifact:report", "type": "produced"},
            {"from": "tool:result:write-report", "to": "memory:report-fact", "type": "produced"},
            {"from": "checkpoint:prompt", "to": "turn:user:2", "type": "checkpointed"},
            {"from": "kv:span:prompt", "to": "checkpoint:prompt", "type": "references"},
        ]
    )

    graph = {
        "graph_id": "graph:local-reference:0001",
        "graph_version": GRAPH_VERSION,
        "created_at": CREATED_AT,
        "agent": {
            "id": AGENT_ID,
            "runtime": RUNTIME_ID,
            "model": MODEL_ID,
            "runtime_version": "0.1.0",
        },
        "participants": [
            {"id": AGENT_ID, "kind": "agent", "name": "Local reference agent", "model": MODEL_ID},
            {"id": USER_ID, "kind": "user", "name": "Local reference user"},
            {"id": TOOL_ID, "kind": "tool", "provider": "local-reference"},
        ],
        "policies": {
            "default_replay_policy": "ask_user",
            "redaction_policy": "required",
            "retention_policy": "durable",
            "required_approval_for_side_effects": True,
        },
        "nodes": nodes,
        "edges": edges,
        "kv_spans": [
            {
                "node_id": "checkpoint:prompt",
                "token_start": 0,
                "token_end": len(prompt_tokens),
                "cache_ref": "kv:simulated:prompt",
                "tokenizer_hash": TOKENIZER_HASH,
                "block_hashes": [token_hash(prompt_tokens)],
            }
        ],
        "graph_hash": "",
    }
    graph["graph_hash"] = canonical_graph_hash(graph)
    return graph


def build_manifest(graph: dict[str, Any], session: LocalSession, prompt: str) -> dict[str, Any]:
    prompt_tokens = tokenize_prompt(prompt)
    artifact_hash = sha256_bytes(session.artifact_bytes)
    return {
        "manifest_version": "0.1",
        "created_at": CREATED_AT,
        "graph_path": "graph.json",
        "graph_hash": graph["graph_hash"],
        "prompt": {
            "reconstruction": "permeant-local-reference-template-v0",
            "byte_hash": sha256_bytes(prompt.encode("utf-8")),
            "token_hash": token_hash(prompt_tokens),
            "tokenizer_hash": TOKENIZER_HASH,
            "token_count": len(prompt_tokens),
        },
        "kv": {
            "mode": "simulated",
            "cache_ref": "kv:simulated:prompt",
            "kv_hash": simulated_kv_hash(prompt_tokens),
        },
        "kv_spans": graph["kv_spans"],
        "artifacts": [
            {
                "path": session.artifact_path,
                "blob_path": f"artifacts/{session.artifact_path}",
                "sha256": artifact_hash,
                "size_bytes": len(session.artifact_bytes),
            }
        ],
        "deterministic_next_response": session.deterministic_response,
    }


def export_session(output_dir: Path) -> dict[str, Any]:
    session = run_reference_session()
    prompt = reconstruct_prompt_from_messages(session.messages)
    artifact_hash = sha256_bytes(session.artifact_bytes)
    graph = build_graph(session, artifact_hash, prompt)
    manifest = build_manifest(graph, session, prompt)

    if output_dir.exists():
        shutil.rmtree(output_dir)
    artifact_file = output_dir / "artifacts" / session.artifact_path
    artifact_file.parent.mkdir(parents=True, exist_ok=True)
    artifact_file.write_bytes(session.artifact_bytes)
    write_json(output_dir / "graph.json", graph)
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def verify_graph(graph: dict[str, Any], expected_hash: str) -> None:
    actual_hash = canonical_graph_hash(graph)
    if actual_hash != expected_hash:
        raise ImportVerificationError(f"graph hash mismatch: expected {expected_hash}, got {actual_hash}")
    if graph.get("graph_hash") != expected_hash:
        raise ImportVerificationError("graph hash field does not match manifest")


def verify_artifacts(package_dir: Path, manifest: dict[str, Any]) -> None:
    for artifact in manifest["artifacts"]:
        blob = package_dir / artifact["blob_path"]
        if not blob.exists():
            raise ImportVerificationError(f"missing artifact blob: {artifact['blob_path']}")
        data = blob.read_bytes()
        actual_hash = sha256_bytes(data)
        if actual_hash != artifact["sha256"]:
            raise ImportVerificationError(
                f"artifact hash mismatch for {artifact['path']}: expected {artifact['sha256']}, got {actual_hash}"
            )
        if len(data) != artifact["size_bytes"]:
            raise ImportVerificationError(f"artifact size mismatch for {artifact['path']}")


def import_session(package_dir: Path) -> dict[str, Any]:
    manifest = read_json(package_dir / "manifest.json")
    graph = read_json(package_dir / manifest["graph_path"])
    verify_graph(graph, manifest["graph_hash"])
    verify_artifacts(package_dir, manifest)

    prompt = reconstruct_prompt(graph)
    prompt_tokens = tokenize_prompt(prompt)
    prompt_byte_hash = sha256_bytes(prompt.encode("utf-8"))
    prompt_token_hash = token_hash(prompt_tokens)
    kv_hash = simulated_kv_hash(prompt_tokens)

    if prompt_byte_hash != manifest["prompt"]["byte_hash"]:
        raise ImportVerificationError("prompt byte hash mismatch")
    if prompt_token_hash != manifest["prompt"]["token_hash"]:
        raise ImportVerificationError("prompt token hash mismatch")
    if kv_hash != manifest["kv"]["kv_hash"]:
        raise ImportVerificationError("simulated KV hash mismatch")

    artifact_hash = manifest["artifacts"][0]["sha256"]
    continuation = deterministic_continue(prompt, artifact_hash)
    if continuation != manifest["deterministic_next_response"]:
        raise ImportVerificationError("deterministic continuation mismatch")

    return {
        "graph_hash": graph["graph_hash"],
        "artifact_hashes": {artifact["path"]: artifact["sha256"] for artifact in manifest["artifacts"]},
        "prompt_byte_hash": prompt_byte_hash,
        "prompt_token_hash": prompt_token_hash,
        "kv_hash": kv_hash,
        "deterministic_next_response": continuation,
    }


def command_export(args: argparse.Namespace) -> None:
    manifest = export_session(Path(args.output))
    print(json.dumps({"exported": str(args.output), "graph_hash": manifest["graph_hash"]}, sort_keys=True))


def command_import(args: argparse.Namespace) -> None:
    result = import_session(Path(args.input))
    print(json.dumps(result, indent=2, sort_keys=True))


def command_demo(args: argparse.Namespace) -> None:
    manifest = export_session(Path(args.output))
    result = import_session(Path(args.output))
    print(
        json.dumps(
            {
                "exported": str(args.output),
                "graph_hash": manifest["graph_hash"],
                "imported": result,
            },
            indent=2,
            sort_keys=True,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    export_parser = subcommands.add_parser("export", help="export the deterministic local session")
    export_parser.add_argument("--output", required=True, help="output package directory")
    export_parser.set_defaults(func=command_export)

    import_parser = subcommands.add_parser("import", help="import and verify a package")
    import_parser.add_argument("--input", required=True, help="input package directory")
    import_parser.set_defaults(func=command_import)

    demo_parser = subcommands.add_parser("demo", help="export, import, and verify in one command")
    demo_parser.add_argument("--output", required=True, help="output package directory")
    demo_parser.set_defaults(func=command_demo)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
