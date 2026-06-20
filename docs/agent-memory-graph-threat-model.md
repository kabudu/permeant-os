# Agent Memory Graph Threat Model

This document covers the Phase 8 local Agent Memory Graph security boundary.
It focuses on graph-package import for the local reference harness, not the
USXF tensor transport envelope.

## Assets

- Conversation, prompt, and memory graph content.
- Tool calls, tool results, pending work, and side-effect policy.
- Artifact references and packaged artifact bytes.
- Credential and capability references.
- Graph provenance and import audit evidence.

## Trust Boundary

An exported graph package may be moved between machines or runtimes. The target
must treat the package as untrusted until all hashes, policy checks, and
attestations pass.

The local harness validates:

- Manifest graph hash against `graph.json`.
- Graph root signature metadata against the graph hash.
- Trusted signer ID.
- Provenance chain entry for the imported graph root.
- Target runtime allowlist.
- Tool allowlist.
- Artifact path and restore-target allowlist.
- Rebind-only credential references.
- Absence of raw secret key fields.
- Existing artifact hash, prompt hash, KV hash, vector-memory, and tool replay
  safety checks.

## Threats And Controls

| Threat | Control |
| --- | --- |
| Graph node tampering | Deterministic graph hash and graph-root signature metadata are verified before activation. |
| Artifact tampering | Content-addressed blob hashes and sizes are checked before restore. |
| Secret copying | Raw secret fields such as `secret_value`, `api_key`, `access_token`, `private_key`, and `password` are rejected. |
| Credential exfiltration | Credential nodes must be `external_only`, include a binding hint, and require target rebind. |
| Unsafe target runtime | Import fails if the requested target runtime is not allowlisted. |
| Unsafe tool activation | Import fails if a tool call is outside the allowlist or violates replay policy. |
| Path traversal or unsafe writes | Absolute paths, `..`, and paths outside allowed artifact prefixes are rejected. |
| Missing provenance | Import fails if the security provenance chain is absent or does not match the graph root. |

## Current Limitations

The local graph-root signature is a deterministic test attestation over the
graph hash, signer ID, and policy version. It is suitable for conformance tests
and tamper detection in the local harness, but it is not a production
cryptographic signature. Production graph packages should use a real signing
key and verifier, aligned with the encrypted and signed USXF transport envelope.

The raw-secret scanner is intentionally conservative over known dangerous field
names. It is not a substitute for full content classification or DLP scanning.

Policy hooks are local allowlists. Production deployments should bind them to a
real policy engine, deployment identity, and operator-approved target/runtime
capabilities.
