# charting

A portable [Agent Skill](https://skills.sh) that renders **shadcn/ui-style
charts** — bar, line, area, pie, donut, radar, radial — to PNG from a compact
JSON spec, and extracts the equivalent Recharts/shadcn JSX. It works with any
Agent Skills host (Claude Code, Hermes, Codex, Kilo, nanobot/OpenClaw, and
others).

Source: <https://github.com/kakalition/apollo-pack/tree/main/skills/charting>

Everything executable lives in focused Python scripts under
`charting/scripts/`. The agent composes a spec and runs a script; the script
owns the shadcn tokens, the Recharts layout, and the headless screenshot, and
prints one JSON envelope per run. State — a chart library, settings, and a
render history — lives in a local SQLite database. There is no server and no
network access at render time.

## What it does

- Renders a JSON chart spec to PNG with Recharts in headless Chromium.
- Families: `bar`, `line`, `area`, `pie`, `donut`, `radar`, and `radial`.
- The static variants of the shadcn/ui chart gallery: curve types (`linear`,
  `step`, `monotone`), percentage `stacked`/`expand`, `axes` and `legend`
  toggles, bar/line `labels`, `negative` and `active` bars, pie `separator`,
  `label-list`, `donut`, and `stacked` rings, radar grid shapes and
  `lines-only`, and radial `grid`, `labels`, and `stacked` rings.
- Faithful shadcn styling: hairline grid, no axis lines, rounded bars, token
  palette (`--chart-1..5`), light and dark themes, card chrome, and a system
  sans-serif by default.
- Palettes: `default` (modern violet), `neutral`, `blue`, `emerald`, `amber`,
  `rose`, `slate` — or your own array / token overrides.
- Deterministic output: animations off, fixed viewport, exact
  `width*scale` × `height*scale` pixels, optional transparency.
- `component` emits the equivalent `recharts` + `@/components/ui/chart` JSX.
- `--register` copies a PNG into the pdf-creator asset store.
- Emits host-agnostic scheduling artifacts and installs nothing.

## Install

With the skills.sh CLI:

```bash
npx --yes skills@latest add kakalition/apollo-pack \
  --skill charting --agent <your-agent> --copy --yes
```

Manual install: copy the `charting/` folder into your host's skills
directory so that `charting/SKILL.md` is discoverable. The folder name must
stay `charting`.

## Quick start

```bash
SKILL=./charting

# state, database, and the one-time Node install (network)
python3 "$SKILL/scripts/init.py" init --install
python3 "$SKILL/scripts/settings.py" set --palette default --legend bottom

# render a bundled example
python3 "$SKILL/scripts/themes.py" demo bar --out bar.png

# or a spec of your own
python3 "$SKILL/scripts/render.py" render --spec chart.json --out chart.png

# extract the react/recharts source
python3 "$SKILL/scripts/render.py" component --spec chart.json
```

A stored chart re-renders by name and takes variables:

```bash
python3 "$SKILL/scripts/charts.py" save --name revenue --spec chart.json
python3 "$SKILL/scripts/render.py" render --doc revenue \
  --var who="Northwind" --out revenue.png --force
```

## Requirements

- Python 3.9 or newer (standard library only).
- **Node 20+** for rendering. `init.py init --install` runs `npm ci`, builds the
  esbuild bundle, and installs Chromium with Playwright. Pinned packages:
  `react`, `react-dom`, `recharts`, `playwright`, and `esbuild` (dev).
- A writable data root (default `~/.local/share/charting`).

`node_modules/` and `scripts/vendor/` are generated and gitignored;
`package.json` and `package-lock.json` are committed. Without Node or the
bundle, `render` fails fast with `dependency_missing`; every other verb works.

## The chart spec

```json
{
  "spec_version": 1,
  "chart": "bar",
  "title": "Revenue by month",
  "data": [
    {"month": "Jan", "desktop": 186, "mobile": 80},
    {"month": "Feb", "desktop": 205, "mobile": 120}
  ],
  "x": {"key": "month"},
  "y": {"hide": false, "format": "number"},
  "series": [
    {"key": "desktop", "label": "Desktop"},
    {"key": "mobile", "label": "Mobile"}
  ],
  "palette": "default",
  "legend": "bottom",
  "width": 720, "height": 420, "scale": 2,
  "background": "transparent"
}
```

See `references/schema.md` for the full reference, `references/charts.md` for
per-family options and the gallery-variant knobs, and `references/themes.md` for
the tokens and palettes.

## Where the data lives

Resolved in order: `--home DIR`, `$CHARTING_HOME`, then
`~/.local/share/charting`. The one directory holds:

```
charting/
├── charting.db        # chart library, settings, render history
├── output/            # default PNG destination
└── tmp/               # generated HTML (kept only with --keep-html)
```

Back up by copying that directory. No personal data is stored in this
repository.

## Compose with pdf-creator

`render.py render --register` copies the rendered PNG into the pdf-creator asset
store (`$PDF_CREATOR_HOME/assets` or `~/.local/share/pdf-creator/assets`) and
returns the asset name. A pdf-creator spec then embeds it by bare file name:

```json
{ "type": "image", "src": "revenue.png", "width": "100%" }
```

There is no code coupling; both skills stay independent.

## Automate a recurring render

```bash
python3 "$SKILL/scripts/render.py" schedule-hint \
  --doc revenue --out ~/reports/revenue.png \
  --target generic --path-mode abs --tz Asia/Jakarta --name revenue-daily
```

`schedule-hint` is read-only and installs nothing; it emits the commands and
routes for your host to register. See `references/scheduling.md`.

## Layout

```
skills/charting/
├── SKILL.md
├── README.md
├── LICENSE
├── .gitignore
├── requirements.txt
├── package.json
├── package-lock.json
├── scripts/            # _lib.py, _html.py + one script per domain
│   ├── _chart.html     # HTML template
│   ├── _chart.css      # CSS template
│   ├── boot/chart-boot.js
│   ├── build.mjs
│   ├── screenshot.mjs
│   └── vendor/         # generated bundle (gitignored)
├── references/         # schema, commands, charts, themes, scheduling
└── tests/smoke.sh
```

## Test

```bash
bash tests/smoke.sh
```

The harness generates its own fixtures, then runs every script and verb against
a throwaway data root and checks the JSON envelope, the chart library, palettes
and themes, validation, component extraction, PNG introspection, the scheduler
artifact matrix (executing the emitted report command twice), and error
handling. It self-skips the render sections when Node, the bundle, or Chromium
are absent, so it passes on a bare host.

## License

MIT. See `LICENSE`.
