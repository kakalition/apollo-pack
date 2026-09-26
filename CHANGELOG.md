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

### Changed

- Fixed `pdf-creator` table-of-contents indentation: level-1 entries were
  shifted right by one level (an off-by-one between heading levels and
  reportlab's zero-based TOC styles), so entries did not line up with the
  "Contents" title. Level-1 entries are now flush left and `toc2`/`toc3` indent
  the levels they were written for.
- Fixed `pdf-creator` TOC and outline navigation: page furniture is drawn at
  save time, which left reportlab's page counter at its initial value, so every
  TOC link and bookmark pointed at the first page. The counter now tracks pages
  during the build and restarts at one when the deferred pages are committed,
  so links jump to the section they name.
- Added `page_break_headings` to `pdf-creator` specs (and the per-heading
  `page_break` option) so every section at a chosen heading level starts on its
  own page; breaks collapse at the top of a page so no blank page is added.
- Repositioned the pack as a **self-development pack for agents**: README hero,
  highlights, and a five-pillar overview (consistency, reflection, money,
  learning, craft).
- Refined `pdf-creator` page furniture to common print/UX best practice: the
  running header now sits about 0.5in from the top edge with a clear ~9mm gap
  between its rule and the first line of content, and the footer page number
  sits about 0.5in from the bottom edge instead of high in the body.
- Extracted the `nanobot-live-status` plugin into its own repository
  (<https://github.com/kakalition/nanobot-live-status>). The pack now contains
  Agent Skills only; `plugins/`, the plugin CI job, and the plugin release
  artifact were removed.

### Removed

- Removed the `charting` skill from the pack. It now lives as a standalone,
  stateless MCP server at `~/Workspaces/agent-mcps/apollo-charting`, exposing
  only `render_chart`, `validate_spec`, and `chart_component`; the pack README,
  catalog, scheduling docs, and CI no longer reference it.

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
