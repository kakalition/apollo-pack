# Changelog

All notable changes to apollo-pack are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the pack adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Items keep their
own versions; the pack version is the root `VERSION` file.

## [Unreleased]

### Added

- New `pdf-creator` skill: render a JSON document spec or a Markdown file to a
  production-grade PDF with rich layout, tables, images, embedded fonts, a
  table of contents, multi-column sections, page headers/footers/watermarks,
  and optional encryption. Adds reportlab to the pack's per-skill requirements.
- New `charting` skill: render shadcn/ui-style bar, line, area, pie, donut,
  radar, and radial charts to PNG from a JSON spec with Recharts in headless
  Chromium, and extract the equivalent shadcn/Recharts JSX. State, validation,
  and reports are standard library Python; only rendering needs Node 20+ with
  the skill's pinned `package.json`.

### Changed

- Repositioned the pack as a **self-development pack for agents**: README hero,
  highlights, and a six-pillar overview (consistency, reflection, money,
  learning, craft, visualization).
- Refined `pdf-creator` page furniture to common print/UX best practice: the
  running header now sits about 0.5in from the top edge with a clear ~9mm gap
  between its rule and the first line of content, and the footer page number
  sits about 0.5in from the bottom edge instead of high in the body.
- Extracted the `nanobot-live-status` plugin into its own repository
  (<https://github.com/kakalition/nanobot-live-status>). The pack now contains
  Agent Skills only; `plugins/`, the plugin CI job, and the plugin release
  artifact were removed.

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
