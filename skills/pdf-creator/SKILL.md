---
name: pdf-creator
description: Create production-grade PDFs from a JSON document spec or Markdown, with rich layout, tables, images, fonts, and page furniture.
version: 1.0.0
author: kakalition (GitHub)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [PDF, Documents, Layout, Tables, Images, Typesetting, Local-First]
    category: productivity
    related_skills: []
---

# PDF Creator Skill

Turn a structured document spec — or a Markdown file — into a polished,
multi-page PDF. The skill owns page geometry, flowable layout, styles, fonts,
image embedding, tables, multi-column sections, headers and footers, a table of
contents, and optional encryption; the host agent only composes a JSON spec (or
writes Markdown) and runs a script. Everything is local: no network access
unless a spec points at a remote image and the caller passes `--allow-remote`.

The renderer is [reportlab](https://www.reportlab.com/) (`requirements.txt`).
Every other verb — state, the document library, the asset store, validation,
and reports — is standard library only and keeps working without it.

## When to Use

- The user wants to produce a PDF: a report, invoice, letter, resume, contract,
  one-pager, certificate, checklist, or multi-column article.
- The user wants Markdown or notes turned into a clean PDF.
- The user wants to embed images, draw tables, control page size and margins,
  add headers, footers, page numbers, watermarks, a table of contents, or
  password-protect the result.
- The user wants to reuse or re-render a document later, or on a schedule.

Skip it for interactive forms, PDF editing or merging of existing files, and
anything that needs a rendered browser (complex CSS, web fonts, or arbitrary
HTML). It composes documents; it does not read or edit existing PDFs beyond a
small metadata/page-count inspection.

## Prerequisites

- Python 3.9+. State, library, asset, and validation verbs are standard
  library only.
- `reportlab` for rendering, plus optional `Pillow` for extra image formats,
  EXIF orientation, and downscaling. Install with
  `pip install -r requirements.txt`. Without reportlab, `render` and
  `templates.py demo` fail fast with a `dependency_missing` error; every other
  verb still works.
- `pypdf` is optional and only used by `reports.py inspect` to read an existing
  PDF's page count and metadata.
- A writable data root (default `~/.local/share/pdf-creator`) holding the
  database, `assets/`, `fonts/`, and `output/`. Override with `--home DIR` or
  `PDF_CREATOR_HOME`.

## How to Run

Resolve the directory that contains this `SKILL.md`, then call a script through
`terminal`:

```
python3 <skill-dir>/scripts/<domain>.py <verb> [flags]
```

- `<domain>` is one of `init`, `settings`, `documents`, `assets`, `templates`,
  `render`, `reports`.
- Every script accepts `--home DIR`, `--format json|table`, `--tz ZONE`, and
  `--quiet`, and prints one JSON envelope per run.
- If `ok` is false, read `error.message` and fix the call instead of guessing.
- Open `references/commands.md` with `read_file` for every flag, and
  `references/schema.md` for the full spec.

First run:

```
python3 <skill-dir>/scripts/init.py init
python3 <skill-dir>/scripts/settings.py set --theme report --margin 20mm
```

Render the smallest document:

```
python3 <skill-dir>/scripts/render.py render --spec doc.json --out out.pdf
```

Or from Markdown:

```
python3 <skill-dir>/scripts/render.py from-markdown --in notes.md --out notes.pdf --toc
```

## Quick Reference

| The user wants to... | Run |
|---|---|
| set up the data root | `init.py init` |
| set defaults (page size, margins, theme, fonts) | `settings.py show\|get\|set` |
| store, list, show, rename, copy, export a spec | `documents.py save\|list\|show\|rename\|duplicate\|export\|delete` |
| register a reusable image or font | `assets.py add-image\|add-font\|list\|remove\|paths` |
| list themes and example documents | `templates.py list\|show\|spec\|demo` |
| render a spec or stored document | `render.py render --spec F\|--doc NAME` |
| render Markdown | `render.py from-markdown --in F --out F` |
| validate a spec | `render.py check --spec F [--strict]` |
| emit a scheduler artifact | `render.py schedule-hint --doc NAME --target ...` |
| see render history, inspect a PDF | `reports.py history\|show\|storage\|stats\|inspect` |

Run `--help` on any domain for every flag, or read `references/commands.md`.

## The document spec

A spec is a JSON object. The important keys:

- `meta` — `title`, `author`, `subject`, `keywords`, `language` (embedded in
  the PDF).
- `page` — `size` (`A4`, `Letter`, `210x297mm`, ...), `orientation`,
  `margins` (one value, or an object with `top`/`right`/`bottom`/`left`).
- `theme` — a built-in theme name or an inline theme object. Themes are modern
  and sans-serif by default; set `font.family` to a serif family only when a
  formal look is wanted.
- `styles` — per-style overrides (font size, color, spacing, alignment).
- `fonts` — TTF/OTF families to embed, each with optional bold/italic faces.
- `header`, `footer` — running text supporting `{page}`, `{pages}`, `{date}`,
  `{title}`, `{author}`.
- `watermark`, `page_numbers`, `toc`, `cover`, `security`.
- `number_headings` (auto-number headings) and `page_break_headings` (start
  each heading at the given level on its own page — `1`, `[1, 2]`, or `true`);
  a single heading can opt in with `"page_break": true`.
- `content` — the ordered list of blocks.

Every length accepts a unit suffix (`pt`, `px`, `in`, `cm`, `mm`, `pc`) or a
percentage where a container is known; a bare number uses the `page.unit`
(default `mm`) for block geometry and points for style sizes. Colors accept
`#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb()`, `rgba()`, and common names.

Block types: `heading`, `paragraph`, `rich`, `list`, `table`, `image`,
`figure`, `code`, `callout`, `blockquote`, `divider`/`hr`, `spacer`,
`page_break`, `page_template`, `columns`, `toc`, `checkbox_list`,
`definition_list`, `key_values`, `anchor`, `qr`, `barcode`. See
`references/layout.md` for a worked example of each.

## Procedure

① **Initialize once.** Run `init.py init`, then persist a house style with
`settings.py set` (page size, margins, theme, base font). Defaults apply to
every render unless a spec overrides them.

② **Compose the spec.** Build a JSON object with `meta`, `page`, an optional
`theme`, and a `content` list. Start from `templates.py spec report --out F` or
another demo, then edit. Prefer semantic blocks (`heading`, `list`, `table`)
over hand-placed spacing.

③ **Add assets when needed.** Register images and fonts once with
`assets.py add-image` / `add-font`, then refer to them by bare file name
(`"src": "logo.png"`). Relative paths resolve against the spec file's folder,
so a spec and its images can live together.

④ **Validate, then render.** Run `render.py check --spec F --strict` to resolve
fonts, images, and every block without writing a PDF, then
`render.py render --spec F --out out.pdf`. Use `--var NAME=VALUE` to fill
`{{NAME}}` placeholders for invoices and letters.

⑤ **Reuse and report.** `documents.py save --name N --spec F` stores a spec so
it can be re-rendered with `--doc N`; each render is recorded and can be listed
with `reports.py history`.

⑥ **Automate only when asked.** `render.py schedule-hint` emits an artifact
that re-renders a stored document; it installs nothing. See
`references/scheduling.md` for the target matrix.

## Pitfalls

- **Do not recompute layout by hand.** Page counts, table wrapping, and TOC
  page numbers come from the renderer. Read `pages` from the JSON, never guess.
- **Percentages need a base.** `width: "50%"` is relative to the text frame;
  it is invalid on a page margin. Use an absolute length there.
- **Bare numbers are not points in every context.** Block geometry uses
  `page.unit` (default `mm`); style sizes and leading are points. Add a suffix
  when unsure.
- **Missing images fail the render.** A missing `src` returns `not_found` and
  writes no PDF. Use `check --strict` before rendering unattended jobs.
- **Remote images are off by default.** Fetching a URL needs `--allow-remote`
  (or `settings.py set --allow-remote yes`); local paths and `data:` URIs never
  need it.
- **`columns` is for short, balanced content.** For a long multi-column
  section, switch page templates with `{"type":"page_template","name":"two_column"}`
  so text flows across frames and pages.
- **Encryption is one-way here.** Set passwords in `spec.security`; the skill
  can create a protected PDF but `reports.py inspect` needs `--password` to read
  it back.
- **Rendering overwrites with `--force`.** The scheduler artifact uses
  `--force`; a manual render without it refuses to clobber an existing file.

## Verification

```bash
python3 <skill-dir>/scripts/render.py check --spec <spec> --strict
python3 <skill-dir>/scripts/reports.py history --limit 1
```

Green means `check --strict` reports `valid: true` with `flowables > 0`, and
`history` returns `read_only: true` with a `renders` list. The test harness
`tests/smoke.sh` runs every verb end to end, including rendering a cover, table
of contents, tables, images, multi-column sections, QR and barcode blocks, and
an encrypted PDF.
