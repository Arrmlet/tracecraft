# Security Policy

tracecraft's core promise is that your agents' data stays in storage **you** own and
govern. We take reports that threaten that promise seriously.

## Reporting a vulnerability

Please report vulnerabilities **privately** via
[GitHub Security Advisories](https://github.com/Arrmlet/tracecraft/security/advisories/new)
— do not open a public issue for security problems.

You can expect an acknowledgement within **72 hours** and a fix or mitigation plan
within **14 days** for confirmed issues. Credit is given in the release notes unless
you prefer otherwise.

## Supported versions

| Version | Supported |
|---|---|
| latest release (0.2.x) | ✅ |
| older | ❌ — please upgrade |

## Scope notes

- **Redaction**: session mirroring scrubs known token shapes (AWS, Anthropic, OpenAI,
  HF, GitHub, Slack) before upload. Bypasses of the redaction patterns are in scope.
- **Bucket privacy**: `init` creates HuggingFace buckets private by default and warns
  on pre-existing public buckets. Anything that silently makes coordination data or
  transcripts public is in scope.
- **No telemetry**: tracecraft sends data only to the bucket you configure. Any code
  path that sends data anywhere else is in scope.
- Credentials are read from environment variables / local config (`.tracecraft.json`,
  mode `600`, auto-gitignored). Reports about handling of those files are welcome.
