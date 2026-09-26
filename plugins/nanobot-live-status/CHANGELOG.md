# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-26

### Added

- Initial release.
- `live_status` tool plugin that subscribes to nanobot's local bus and shows a
  single rotating status sentence per Telegram turn, edited in place and
  deleted when the turn completes.
- Shuffled action × object × emoji phrase deck (ported from Lattice), with
  `NANOBOT_LIVE_STATUS_PHRASES` override.
- Environment controls for interval, phrases, keep-vs-delete, and disable.
- Crash-safe, guarded nanobot internals imports; no-op on drifted hosts.
- `nanobot-live-status doctor` diagnostics CLI; token is never printed.

[Unreleased]: https://github.com/kakalition/apollo-pack/commits/main/plugins/nanobot-live-status
[0.1.0]: https://github.com/kakalition/apollo-pack/releases/tag/v0.1.0
