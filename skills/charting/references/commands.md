# Commands

Every script prints one JSON envelope per run:

```json
{ "ok": true, "command": "<domain>.<verb>", "data": { ... } }
```

On failure it prints `{"ok": false, "error": {"code", "message"}}` and exits `1`
(`2` on an argparse usage error). Every script accepts `--home DIR`,
`--format json|table`, `--tz ZONE`, and `--quiet`.

## init.py

| Verb | Flags | Notes |
|---|---|---|
| `init` | `--install` | Create the data root, database, `output/`, and `tmp/`; report Node/bundle/Playwright/Chromium. `--install` runs `npm ci`, builds the bundle, and downloads Chromium. |

## settings.py

| Verb | Flags |
|---|---|
| `show` | — |
| `get` | `--key NAME` |
| `set` | `--theme light\|dark`, `--palette NAME`, `--width N`, `--height N`, `--scale N`, `--background transparent\|COLOR`, `--font PATH`, `--grid on\|off`, `--legend top\|bottom\|right\|none`, `--output-dir DIR` |

Namespaced overrides: `CHARTING_HOME`, `CHARTING_THEME`,
`CHARTING_PALETTE`, `CHARTING_WIDTH`, `CHARTING_HEIGHT`,
`CHARTING_SCALE`, `CHARTING_BACKGROUND`, `CHARTING_FONT`,
`CHARTING_GRID`, `CHARTING_LEGEND`, `CHARTING_OUTPUT_DIR`.

## charts.py

| Verb | Flags |
|---|---|
| `save` | `--name N` (required), `--spec FILE` \| `--stdin`, `--title T`, `--tags a,b`, `--force` |
| `list` | `--tag T`, `--family FAMILY` |
| `show` | `NAME` |
| `rename` | `NAME NEW_NAME` |
| `duplicate` | `NAME NEW_NAME` `--force` |
| `delete` | `NAME` `--yes` |
| `export` | `NAME` `--out FILE` |

## themes.py

| Verb | Flags |
|---|---|
| `list` | — |
| `show` | `NAME` `--kind palette\|theme\|demo` |
| `spec` | `NAME` `--out FILE` |
| `demo` | `NAME` `--out FILE` `--scale N` `--theme light\|dark` `--transparent` |

## render.py

| Verb | Flags |
|---|---|
| `render` | `--spec FILE` \| `--doc NAME`, `--var NAME=VALUE` (repeatable), `--out FILE`, `--scale N`, `--theme light\|dark`, `--transparent`, `--register`, `--pdf-home DIR`, `--force`, `--keep-html`, `--no-record` |
| `check` | `--spec FILE` \| `--doc NAME`, `--var`, `--strict` |
| `component` | `--spec FILE` \| `--doc NAME`, `--var`, `--out FILE` |
| `schedule-hint` | `--spec FILE` \| `--doc NAME`, `--out FILE`, `--target`, `--path-mode`, `--at-time HH:MM`, `--name`, `--action`, `--job` |

`render` data includes `out`, `bytes`, `sha256`, `width`, `height`, `scale`,
`family`, `theme`, `background`, `html` (only with `--keep-html`), `warnings`,
`render_id` (unless `--no-record`), and — with `--register` — a `register` object
with `asset` and `asset_path`.

## reports.py

| Verb | Flags |
|---|---|
| `history` | `--limit N`, `--doc NAME`, `--detail` |
| `show` | `RENDER_ID` |
| `storage` | — |
| `stats` | — |
| `inspect` | `FILE` |

`inspect` reads the PNG IHDR with the standard library only (no Pillow) and
returns `width`, `height`, `bit_depth`, `color_type`, `color_type_name`,
`bytes`, and `sha256`.
