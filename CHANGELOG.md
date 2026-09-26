# Changelog

All notable changes to apollo-pack are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the pack adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Items keep their
own versions; the pack version is the root `VERSION` file.

## [Unreleased]

## [0.1.0] - 2026-09-26

### Added

- Initial monorepo pack: four Agent Skills under `skills/` and the
  `nanobot-live-status` plugin under `plugins/`.
- Generated `catalog.json` and README catalog block via `tools/catalog.py`
  (`build` and `check`).
- Pack CI (catalog check, per-skill smoke tests, plugin lint/type/tests, secret
  scan) and a release workflow.

### Changed

- The scheduler-latch contract moved from the root `README.md` to
  `docs/scheduling.md`; example paths point at the new `skills/<id>/` layout.
- Each item's documentation was repointed at the pack monorepo.

[Unreleased]: https://github.com/kakalition/apollo-pack/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kakalition/apollo-pack/releases/tag/v0.1.0
