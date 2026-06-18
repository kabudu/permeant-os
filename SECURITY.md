# Security Policy

PermeantOS moves sensitive AI agent state, including prompts, tool outputs, intermediate activations, and potentially references to credentials or private artifacts. Treat migration artifacts as sensitive by default.

## Supported versions

PermeantOS is currently a research preview. Security fixes will target the main development branch until versioned releases are established.

## Reporting vulnerabilities

Please report suspected vulnerabilities privately to the project maintainer before public disclosure. If no private security channel is configured yet, open a GitHub issue with minimal non-sensitive detail requesting a private disclosure path.

Do not include:

- Real user prompts or conversations.
- API keys or cloud credentials.
- Private model weights.
- Migration manifests containing sensitive context.
- Exploit payloads against third-party services.

## Security-sensitive areas

- Encryption and signature envelope.
- Migration manifest contents.
- Runtime adapter hooks.
- Cloud provisioning scripts.
- SSH tunnel setup.
- Prefix-cache and KV block attachment logic.
- Future Agent Memory Graph export/import.

## Operational guidance

- Run cloud E2E tests in disposable environments.
- Verify cleanup of instances, security groups, keys, and local PEM files.
- Avoid exposing the daemon directly to the public internet.
- Prefer SSH tunnels or private networking for remote validation.
- Redact manifests before sharing when they contain real prompts or model state.
