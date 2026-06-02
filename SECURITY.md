# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in the Tain Agent Framework, please
report it privately by opening a GitHub Security Advisory in this repository.

We take all security reports seriously and will respond within 7 days.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.5.x   | Yes       |
| < 0.5.0 | No        |

## Security Model

Tain Agent Framework runs AI agents that can execute tools with filesystem
and network access. Key security boundaries:

- **Workspace isolation**: each agent operates in its own directory under
  `agent_workspace/<name>/`
- **Tool forging sandbox**: 7-stage pipeline with AST-level import/call
  filtering and subprocess isolation
- **Self-modification protection**: critical framework files are protected
  from modification by agents
- **API authentication**: Web UI supports API key authentication via
  `TAIN_API_KEY` environment variable
- **Rate limiting**: chat endpoint is rate-limited at 60 requests/minute per
  IP address

See [docs/SAFETY.md](docs/SAFETY.md) for the full safety model documentation,
including known limitations and attack surface analysis.
