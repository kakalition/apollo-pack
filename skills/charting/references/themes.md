# Themes and palettes

The renderer injects the full shadcn token set as CSS custom properties and reads
them from the Recharts elements. `theme` selects the neutral surface tokens;
`palette` selects `--chart-1..5`.

## Surface tokens

| Token | Light | Dark |
|---|---|---|
| `--background` | `#ffffff` | `#09090b` |
| `--foreground` | `#111827` | `#fafafa` |
| `--card` | `#ffffff` | `#111113` |
| `--card-foreground` | `#111827` | `#fafafa` |
| `--muted` | `#f4f4f5` | `#27272a` |
| `--muted-foreground` | `#71717a` | `#a1a1aa` |
| `--border` | `#e4e4e7` | `#27272a` |
| `--input` | `#e4e4e7` | `#27272a` |
| `--ring` | `#7c3aed` | `#a78bfa` |
| `--radius` | `10px` | `10px` |

The neutral palette is deliberately restrained and sans-serif, matching the
pack's modern house style (near-black type, a single violet accent, hairline
rules). There is no serif fallback.

## Palette presets

| Name | Colors (`--chart-1..5`) |
|---|---|
| `default` | `#7c3aed` `#a78bfa` `#60a5fa` `#34d399` `#fbbf24` |
| `neutral` | `#18181b` `#52525b` `#a1a1aa` `#d4d4d8` `#e4e4e7` |
| `blue` | `#2563eb` `#60a5fa` `#93c5fd` `#38bdf8` `#0ea5e9` |
| `emerald` | `#059669` `#34d399` `#6ee7b7` `#10b981` `#14b8a6` |
| `amber` | `#d97706` `#f59e0b` `#fbbf24` `#fcd34d` `#fb923c` |
| `rose` | `#e11d48` `#fb7185` `#fda4af` `#f472b6` `#be123c` |
| `slate` | `#334155` `#64748b` `#94a3b8` `#cbd5e1` `#0f172a` |

`default` leads with the modern violet `#7c3aed` family. Presets always define
all five tokens; short arrays cycle.

## Choosing a palette in a spec

```json
"palette": "emerald"
```

```json
"palette": ["#7c3aed", "#22d3ee"]
```

```json
"palette": {"chart-1": "#0f766e", "chart-2": "#5eead4"}
```

Per-series overrides win over the palette:

```json
"series": [
  {"key": "a", "label": "A", "color": "chart-3"},
  {"key": "b", "label": "B", "color": "#111827"}
]
```

`color` accepts a token (`chart-1` or `--chart-1`) or any CSS color.

## Fonts

The default `font` is a system sans stack
(`-apple-system, "Segoe UI", Inter, ...`). Point `font` at a TTF/WOFF2 file next
to the spec to embed it offline:

```json
{ "font": "Inter-Regular.ttf" }
```

The file is base64-embedded as an `@font-face` rule, so the PNG needs no network.
If the file is missing the renderer falls back to the system stack.

## Inspecting

```bash
python3 scripts/themes.py list
python3 scripts/themes.py show default            # palette colors
python3 scripts/themes.py show dark --kind theme  # token map
python3 scripts/settings.py set --palette blue --theme dark --legend right
```
