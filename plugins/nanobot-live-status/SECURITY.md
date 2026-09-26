# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's
[security advisories](https://github.com/kakalition/apollo-pack/security/advisories/new)
rather than in a public issue. Include steps to reproduce and the affected
version. We aim to acknowledge reports within a few days.

## Secrets

- The Telegram bot token is read from nanobot's config (`~/.nanobot/config.json`)
  or from `NANOBOT_LIVE_STATUS_TOKEN` at runtime. It is never logged, printed,
  or included in error messages. Telegram request URLs embed the token, so
  network errors are reported by exception type only.
- The plugin never writes to nanobot's config, session storage, or memory.

## Scope

This is an independent, third-party plugin, not affiliated with the nanobot
project. Vulnerabilities in nanobot itself should be reported to that project.

## Supported versions

Only the latest released version receives security fixes.
