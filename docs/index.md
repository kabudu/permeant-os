# PermeantOS Documentation Hub

PermeantOS is a validated early platform for live AI agent state migration.
This hub maps the repository documentation by task so new users and
contributors can get from installation to evidence to adapter work without
reading the whole history.

## Start Here

- [README](../README.md): project status, supported paths, and quick start.
- [Deployment and testing guide](deployment-and-testing-guide.md): local daemon,
  simulated migration, benchmark collection, and cloud-host workflows.
- [Release artifacts](release-artifacts.md): build checksummed binary bundles,
  verify archives, and install `permeant-cli`.
- [Crate and SDK publication plan](crate-and-sdk-publication-plan.md): package
  metadata, publish-disabled gating, and future registry release steps.
- [Versioning policy](versioning-policy.md): schema, report, artifact, and
  lightweight release versioning rules.

## Evidence And Claims

- [Evidence index](evidence-index.md): public claim-to-proof map with commands,
  CI jobs, and known limitations.
- [Model/runtime validation matrix](model-runtime-validation-matrix.md):
  validated and planned model-family/runtime profiles.
- [AWS long-horizon proof](aws-real-runtime-long-horizon-2026-06-21.md):
  Qwen2.5 MLX-to-AWS-vLLM 128-token continuation evidence.
- [TinyLlama AWS proof](aws-real-runtime-tinyllama-2026-06-21.md):
  raw-transfer non-Qwen structural E2E validation.
- [llama.cpp canonical KV proof](llama-cpp-cross-runtime-canonical-kv-proof-2026-06-21.md):
  local MLX-to-llama.cpp canonical KV feed evidence.

## Runtime And Adapter Authors

- [Runtime adapter protocol](runtime-adapter-protocol.md): command-backed
  extractor/injector contract.
- [Agent framework adapters](agent-framework-adapters.md): capability manifests,
  compatibility matrix, and conformance rules.
- [PyTorch target adapter](pytorch-target-runtime-adapter.md): reference target
  runtime adapter and evidence criteria.
- [llama.cpp target adapter](llama-cpp-target-runtime-adapter.md): llama.cpp
  capability probe, state binding, and raw KV writer boundaries.
- [Target import worker](target-import-worker.md): vLLM target import worker
  contract.

## Agent Memory Graph

- [Agent Memory Graph v0](agent-memory-graph.md): schema specification for
  conversation, tools, artefacts, retrieval memory, pending work, provenance,
  and KV spans.
- [Agent Memory Graph threat model](agent-memory-graph-threat-model.md):
  graph import trust boundaries and policy checks.
- [Graph-attached KV migration plan](graph-attached-kv-migration-plan.md):
  graph/KV transaction binding acceptance criteria.
- [Machine-readable schema](schemas/agent-memory-graph-v0.schema.json): JSON
  Schema served publicly at
  `https://www.permeantos.org/schemas/agent-memory-graph-v0.schema.json`.

## Transport And Cloud Validation

- [Production transport](production-transport.md): secure transport profile,
  binary frames, fallback ladder, and replay rejection.
- [AWS real-runtime E2E runner](aws-real-runtime-e2e-runner.md): preflight,
  run, status, cleanup, and cost controls.
- [AWS prewarm image](aws-prewarm-image.md): conservative bootstrap acceleration
  without always-on infrastructure.

## Benchmarks And Planning

- [Benchmark summary tooling](benchmark-summary-tooling.md): manifest summary
  reports for release notes and evidence tables.
- [Fidelity horizon suite](fidelity-horizon-suite.md): multi-horizon
  continuation comparison.
- [Context benchmark matrix](context-benchmark-matrix.md): larger-context
  planning with target context-window checks.
- [Transfer quantization comparison](transfer-quantization-comparison.md):
  raw-vs-quantized manifest comparisons.
- [Adaptive transfer codecs](adaptive-transfer-codecs.md): raw, FP8, and future
  codec planning with fallback semantics.

## Current Limits

- PermeantOS is pre-1.0; supported claims are bounded to validated paths.
- GitHub Release publishing, crate publishing, signed assets, and Python
  package publishing are not enabled yet.
- QATQ is being matured separately before it is folded back into PermeantOS as
  a production codec.
