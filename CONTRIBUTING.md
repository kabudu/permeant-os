# Contributing to PermeantOS

Thank you for considering a contribution. PermeantOS is a research-preview system for live AI agent state migration, so clarity and reproducibility matter as much as code.

## Good first contribution areas

- Documentation improvements.
- Reproducible local examples.
- Manifest/analyzer improvements.
- Runtime adapter experiments.
- Agent Memory Graph schema review.
- Security and threat-model review.

## Development expectations

Before opening a pull request:

- Keep changes focused.
- Document new runtime assumptions.
- Do not commit secrets, cloud keys, private prompts, or real user context.
- Include reproduction steps for any benchmark or cloud run.
- If a change provisions cloud resources, document cleanup steps.
- Preserve existing manifests and run reports unless intentionally superseding them.

## Local build

```bash
cargo build
```

Before opening a pull request, run the same core checks as PR CI:

```bash
cargo fmt --all -- --check
cargo clippy --locked --all-targets --all-features -- -D warnings
cargo test --locked
python -m pytest tests
python sdk/python/test_sdk.py
```

Run the local simulated daemon and migration in separate terminals:

```bash
./target/debug/permeant-cli daemon --addr 127.0.0.1:9099
```

```bash
./target/debug/permeant-cli sim-migrate --target-addr 127.0.0.1:9099 --seq-len 512
```

## Runtime adapters

Many adapters are Python because MLX and vLLM expose the required runtime internals through Python APIs. Adapter contributions should clearly state:

- Runtime and version tested.
- Model family tested.
- Tensor layout assumptions.
- Tokenizer/prompt-template assumptions.
- How fidelity was validated.

## Pull request checklist

- Explain the motivation and scope.
- Link relevant issue or roadmap item if available.
- Include docs for user-visible behavior.
- Include cleanup instructions for cloud or local background services.
- Note any security-sensitive data paths.
- State whether tests or E2E validation were run.

## Licensing

By contributing, you agree that your contributions are licensed under the Apache License, Version 2.0.
