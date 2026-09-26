# Chart spec reference (schema v1)

A chart spec is a JSON object. `render.py check` validates the schema with the
standard library; `render.py render` renders it with Node + Recharts.

## Top-level keys

| Key | Type | Default | Notes |
|---|---|---|---|
| `spec_version` | int | `1` | Rejected if newer than the skill supports. |
| `chart` | string | — | **Required.** `bar` `line` `area` `pie` `donut` `radar` `radial`. |
| `variant` | string | — | `bar` only: `grouped` `stacked` `horizontal`. |
| `title` / `description` | string | — | Rendered as card chrome above the plot. |
| `data` | array | — | Tabular rows: a list of objects. |
| `categories` | array | — | Labels paired with series `values` when `data` is omitted. |
| `x` | object | — | Category axis. Cartesian charts need `x.key`. |
| `y` | object | — | Value axis. |
| `axis_key` | string | `x.key` | `radar` only. |
| `series` | array | inferred | `[{key, label, color}]` or `[{key, values}]`. |
| `name_key` / `value_key` | string | — | Slice fields for `pie` / `donut` / `radial`. |
| `palette` | string \| array \| object | `default` | Name, 1–5 colors, or `chart-1..5` overrides. |
| `theme` | string | `light` | `light` or `dark`. |
| `legend` | string \| bool | `bottom` | `top` `bottom` `right` `none`; `false` = `none`. |
| `grid` | bool | `true` | Cartesian grid (horizontal lines only). |
| `curve` | string | `monotone` | `linear` `monotone` `stepAfter` `step` `basis` `natural`. |
| `stacked` | bool | `false` | Stack series (`bar` / `area`). |
| `horizontal` | bool | `false` | Horizontal bars. |
| `gradient` | bool | `true` | Area gradient fill. |
| `donut` | bool | `false` | Inner radius for pie charts. |
| `inner_radius` / `outer_radius` | number \| string | family | Percent string or pixels. |
| `fill_opacity` | number | `0.6` | Radar fill opacity. |
| `stroke_width` | number | `2` | Line / area stroke width. |
| `dot` | bool | `false` | Show line dots. |
| `radius` | int | `4` | Bar corner radius. |
| `label` / `labels` | bool | `false` | Value labels on bar/line; slice labels on pie/donut. |
| `expand` | bool | `false` | Percentage stacking (with `stacked`); axis reads 0–100%. |
| `axes` | bool | `false` | Show the value axis (same as `y.hide: false`). |
| `separator` | bool | `true` | Pie slice stroke; `false` removes it. |
| `legend_values` | bool | `false` | Pie legend shows each slice's value. |
| `active` | int | — | 0-based index to highlight (bar dim, pie pop-out). |
| `negative` / `negative_color` | bool / color | `false` / `--chart-2` | Bar values below zero use the negative color. |
| `value_key_2` | string | — | Second ring value for `pie_stacked` (pie/donut/radial). |
| `pie_stacked` | bool | `false` | Two concentric rings. |
| `radar_grid` | string | `polygon` | `polygon` `circle` `none`. |
| `radar_grid_fill` | bool | `false` | Tint the polar grid. |
| `radar_dots` | bool | `false` | Dots on radar vertices. |
| `fill` | bool | `true` | `false` gives an outline-only radar (lines-only). |
| `outer_radius` | number \| string | family | Radar / pie / donut outer radius. |
| `radial_grid` | bool | `false` | Circular polar grid behind radial arcs. |
| `radial_labels` | bool | `false` | Inside labels on radial arcs. |
| `radial_corner` | int | `10` | Radial arc corner radius. |
| `radial_stacked` | bool | `false` | One radial ring per series. |
| `center_label` | string | — | Donut or radial center text. |
| `center_total` | bool | `false` | Radial: show the summed value in the center. |
| `background_track` | bool | `true` | Radial background track. |
| `tooltip` | bool | `false` | Include the Recharts tooltip (invisible in a static PNG). |
| `background` | string | `transparent` | `transparent`, a hex color, or `rgb()`. |
| `card` | bool | `true` | Draw the card border and radius. |
| `padding` | int | `16` | Inner padding in CSS pixels. |
| `width` / `height` | int | `720` / `420` | CSS pixels, 64–4096. |
| `scale` | int | `2` | Device scale, 1–4. The PNG is `width*scale` × `height*scale`. |
| `font` | string | `system` | `system`, or a TTF/WOFF2 path next to the spec (embedded offline). |

## Data shapes

**Tabular (preferred).** Each row is an object. `x.key` names the category
field; each `series.key` names a numeric field. Series are inferred from the
numeric columns when `series` is omitted.

```json
{
  "chart": "bar",
  "data": [{"month": "Jan", "desktop": 186, "mobile": 80}],
  "x": {"key": "month"}
}
```

**Explicit series.** Give each series a `values` array and, optionally,
`categories`. Rows are synthesized in order.

```json
{
  "chart": "line",
  "categories": ["W1", "W2", "W3"],
  "x": {"key": "week"},
  "series": [{"key": "users", "label": "Users", "values": [10, 20, 30]}]
}
```

**Slices.** `pie`, `donut`, and `radial` accept `name_key` + `value_key` over
`data`, or `x.key` plus a single series, or a single series with `values` and
`categories`.

## Axes

```json
{
  "x": {"key": "month", "tick_margin": 8, "hide": false},
  "y": {"label": "", "domain": [0, 300], "format": "number", "hide": false}
}
```

- `y.hide` is `true` by default: shadcn charts hide value-axis lines and ticks.
  Set `"hide": false` to show them.
- `y.format` is one of `number`, `percent`, `currency`, `compact`, `raw`.
- `domain` is passed straight to Recharts (for example `[0, 300]`).

## Errors

`render.py check` returns `invalid_spec` for: unknown `chart`, missing `x.key`
on a cartesian family, a series key absent from `data`, an unknown palette, an
out-of-range `scale`/dimension, a bad color, or a `spec_version` newer than the
skill. It returns `not_found` when a referenced file or stored chart is missing.
