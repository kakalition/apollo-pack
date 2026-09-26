# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's
[security advisories](https://github.com/kakalition/apollo-pack/security/advisories/new)
rather than in a public issue. Include steps to reproduce, the affected item
and version, and any relevant environment details. We aim to acknowledge
reports within a few days.

## Secrets

- `kilo.json` at the repo root stores a local provider API key and is
  gitignored. Never commit it. `kilo.example.json` is the redacted template.
- If a secret is ever committed or pushed, rotate it. Deleting it from the
  working tree or from history is not sufficient once it has been exposed.
- CI runs a secret scan (gitleaks) on every push and pull request; the scan
  allows `*.example.json` so the redacted template does not false-positive.

## Scope

This pack bundles independent Agent Skills. Each skill keeps its own license
and, where present, its own security notes. Vulnerabilities in a host (for
example nanobot) should be reported to that project.

## Supported versions

Only the latest released version of each item receives security fixes.
