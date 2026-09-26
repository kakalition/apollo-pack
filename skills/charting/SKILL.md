---
name: charting
description: Render shadcn/ui-style charts (bar, line, area, pie, donut, radar, radial) to PNG with Recharts in headless Chromium, and extract the equivalent shadcn/Recharts JSX.
version: 1.0.0
author: kakalition (GitHub)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Charts, Recharts, shadcn, Data Visualization, PNG, Local-First]
    category: productivity
    related_skills: [pdf-creator]
---

# charting Skill

Turn a compact JSON chart spec into a **shadcn/ui-style PNG**. The skill owns
the shadcn design tokens (`--chart-1..5`, `--background`, `--foreground`,
`--border`, `--muted-*`, `--radius`), the Recharts element tree, and the headless
Chromium screenshot. The host agent only composes a spec and runs a script.
Everything is local: no network access at render time.

The renderer is **Node + React + Recharts** bundled with esbuild and screenshotted
with **Playwright Chromium**. Every other verb — state, the chart library,
palettes, validation, component extraction, and reports — is standard library
Python and keeps working without Node installed.

## When to Use

- The user wants a polished, modern chart image: bar, line, area, pie, donut,
  radar, or radial.
- The user wants the shadcn/ui look (hairline grid, no axis lines, rounded bars,
  token palette) exported as a PNG for a document, slide, or report.
- The user wants the **react/recharts source** for a chart (`component`).
- The user wants to reuse or re-render a chart later, or on a schedule.

Skip it for interactive dashboards, live-updating charts, animated GIF/MP4, or
SVG-only output. It produces a static image and the equivalent source.

## Prerequisites

- Python 3.9+. State, library, palette, validation, component, and report verbs
  are standard library only.
- **Node 20+** and a one-time install for rendering:
  `python3 scripts/init.py init --install` runs `npm ci`, builds the esbuild
  bundle (`scripts/vendor/chart-bundle.js`), and downloads Chromium. After that,
  rendering is fully offline.
- A writable data root (default `~/.local/share/charting`) holding the
  database, `output/`, and `tmp/`. Override with `--home DIR` or
  `CHARTING_HOME`.
- Without Node or the bundle, `render` fails fast with a `dependency_missing`
  error that includes the exact install command; every other verb still works.

## How to Run

Resolve the directory that contains this `SKILL.md`, then call a script through
`terminal`:

```
python3 <skill-dir>/scripts/<domain>.py <verb> [flags]
```

- `<domain>` is one of `init`, `settings`, `charts`, `themes`, `render`,
  `reports`.
- Every script accepts `--home DIR`, `--format json|table`, `--tz ZONE`, and
  `--quiet`, and prints one JSON envelope per run.
- If `ok` is false, read `error.message` and fix the call instead of guessing.
- Open `references/commands.md` with `read_file` for every flag,
  `references/schema.md` for the spec, `references/charts.md` for per-family
  options, and `references/themes.md` for tokens and palettes.

First run:

```
python3 <skill-dir>/scripts/init.py init --install
python3 <skill-dir>/scripts/settings.py set --palette default --legend bottom
```

Render the smallest chart:

```
python3 <skill-dir>/scripts/render.py render --spec chart.json --out chart.png
```

Or render a bundled example:

```
python3 <skill-dir>/scripts/themes.py demo bar --out bar.png
```

## Quick Reference

| The user wants to... | Run |
|---|---|
| set up the data root and Node deps | `init.py init [--install]` |
| set defaults (theme, palette, size, legend) | `settings.py show\|get\|set` |
| store, list, show, rename, copy, export a spec | `charts.py save\|list\|show\|rename\|duplicate\|export\|delete` |
| list palettes, themes, and demos | `themes.py list\|show\|spec\|demo` |
| render a spec or stored chart | `render.py render --spec F\|--doc NAME` |
| validate a spec | `render.py check --spec F [--strict]` |
| extract the shadcn/Recharts JSX | `render.py component --spec F\|--doc NAME` |
| emit a scheduler artifact | `render.py schedule-hint --doc NAME --target ...` |
| see render history, inspect a PNG | `reports.py history\|show\|storage\|stats\|inspect` |

Run `--help` on any domain for every flag, or read `references/commands.md`.

## The chart spec

A spec is a JSON object. The important keys:

- `chart` — the family: `bar`, `line`, `area`, `pie`, `donut`, `radar`, or
  `radial`.
- `data` — tabular rows (Recharts-native), for example
  `[{"month": "Jan", "desktop": 186, "mobile": 80}]`. Alternatively give
  `series` entries a `values` array plus optional `categories`.
- `x` / `y` — axis options. Cartesian charts need `x.key` naming the category
  field; `y` accepts `domain`, `format` (`number`, `percent`, `currency`,
  `compact`), and `hide` (the y-axis is hidden unless `hide` is `false`).
- `series` — optional `[{key, label, color}]`; omitted series are inferred from
  the numeric columns in `data`.
- `name_key` / `value_key` — slice names and values for `pie`, `donut`, and
  `radial`.
- `palette` — a preset name, an array of 1–5 colors, or a `chart-1..chart-5`
  override object. `theme` is `light` (default) or `dark`.
- `legend` — `top`, `bottom` (default), `right`, or `none`; `grid`, `radius`,
  `curve`, `stacked`, `horizontal`, `gradient`, `fill_opacity`, `dot`,
  `background`, `card`.
- `width`, `height`, `scale`, `padding` — output geometry. The PNG is
  `width*scale` × `height*scale` device pixels.
- `title`, `description` — rendered as shadcn card chrome above the plot.

Colors accept `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb()`, `rgba()`, and common
names. A series `color` may also be a token such as `chart-1`.

## Procedure

① **Initialize once.** Run `init.py init --install`; it creates the data root
and fetches the pinned Node dependencies. Then set house defaults with
`settings.py set` (theme, palette, size, legend).

② **Compose the spec.** Start from `themes.py spec bar --out F` (or any demo),
then edit. Prefer tabular `data` and name `series` explicitly when the auto
inference is ambiguous.

③ **Validate, then render.** `render.py check --spec F` validates the spec with
the standard library; `--strict` also confirms Node, the bundle, and Chromium.
Then `render.py render --spec F --out out.png`. Use `--var NAME=VALUE` to fill
`{{NAME}}` placeholders.

④ **Extract source when asked.** `render.py component --spec F` prints the
equivalent shadcn/Recharts JSX (imports from `recharts` and
`@/components/ui/chart`).

⑤ **Reuse and report.** `charts.py save --name N --spec F` stores a spec so it
can be re-rendered with `--doc N`; each render is recorded and listed by
`reports.py history`. `reports.py inspect` reads any PNG's dimensions with the
standard library.

⑥ **Compose with PDFs.** `render.py render --register` copies the PNG into the
pdf-creator asset store so a PDF spec can embed it with
`{"type":"image","src":"<name>.png"}`.

⑦ **Automate only when asked.** `render.py schedule-hint` emits an artifact
that re-renders a stored chart; it installs nothing. See
`references/scheduling.md` for the target matrix.

## Pitfalls

- **Rendering needs the bundle, not just Node.** If `scripts/vendor/chart-bundle.js`
  is missing, the render returns `dependency_missing` with the exact
  `npm ci` + `build.mjs` command. Re-run it after upgrading a dependency.
- **Dimensions are device pixels.** A `720x420` chart at `scale: 2` is a
  `1440x840` PNG. Always read `width`/`height` from the JSON, never guess.
- **The y-axis is hidden by default.** shadcn charts hide value axis lines and
  ticks; set `"y": {"hide": false}` to show them.
- **Cartesian charts need `x.key`.** Without it the spec is rejected; there is no
  silent first-column fallback.
- **Series keys must exist in `data`.** A typo returns `invalid_spec` rather than
  drawing a blank series.
- **Animations are disabled** so screenshots are deterministic. Do not expect
  motion in the PNG, and do not add CSS transitions to the plot.
- **Transparent is the default background.** Pass a color in `background` for an
  opaque card; `--transparent` forces transparency for one call.
- **Rendering overwrites with `--force`.** The scheduler artifact uses
  `--force`; a manual render without it refuses to clobber an existing file.

## Verification

```bash
python3 <skill-dir>/scripts/render.py check --spec <spec> --strict
python3 <skill-dir>/scripts/reports.py history --limit 1
```

Green means `check --strict` reports `valid: true` and `renderable: true`, and
`history` returns `read_only: true` with a `renders` list. The test harness
`tests/smoke.sh` runs every verb end to end, rendering one chart per family and
checking the PNG dimensions; it self-skips the render sections when Node, the
bundle, or Chromium are absent.
