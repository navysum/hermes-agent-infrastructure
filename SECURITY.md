# Security Policy

Security is a first-class concern in this project — both in how the live system
is operated and in how this repository was prepared for publication.

## How this repository handles secrets

This repo is a **sanitized extract** of a private, live deployment. The
following controls were applied before publishing:

- **No credentials in version control.** All secrets load from a `.env` file
  that is git-ignored. The repo ships only `.env.example` with placeholder keys
  and `config/config.example.yaml` with every sensitive value redacted.
- **No runtime state.** Databases, logs, agent memory, auth tokens, message
  history and cron state are excluded via `.gitignore` — they may contain
  personal data or tokens.
- **Automated secret scanning.** A [gitleaks](https://github.com/gitleaks/gitleaks)
  job runs in CI (`.github/workflows/ci.yml`) on every push and pull request as
  a standing guard against accidental secret commits.
- **Manual review.** Before the initial commit, the working tree was scanned for
  API-key formats (`sk-`, `ghp_`, `xox*`, `AIza*`, bot tokens), private-key
  blocks, connection strings, UUIDs/database IDs, public IPs, emails and other
  personal identifiers.

## Operational security of the live system

- **Read-only money & health.** Financial (OANDA) and health (Whoop)
  integrations are read-only. The agent observes and alerts; it never places
  orders or moves funds. Live trading never routes through an agent.
- **Private management surface.** The dashboard rejects non-local `Host`
  headers and is reachable only over a private Tailscale network via a
  localhost-bound reverse proxy — never exposed to the public internet.
- **Least privilege for tools.** A command allowlist plus an approvals layer
  gate what the agent may execute; secret redaction is enabled on tool output.
- **Token hygiene.** OAuth refresh flows are serialized to avoid burning
  single-use refresh-token chains.

## Reporting a vulnerability

If you believe you have found a security issue in this code, please open a
private report via GitHub Security Advisories on this repository, or contact the
maintainer through the links in the README. Please do not open a public issue
for anything that could expose a credential or personal data.
