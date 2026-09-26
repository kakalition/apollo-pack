# Chart families

Each family maps to a shadcn/ui chart, which is a themed Recharts component. The
renderer emits the same props the shadcn registry uses so the PNG matches the web
component.

| Family | Recharts base | Key options |
|---|---|---|
| `bar` | `BarChart` + `Bar` | `variant` (`grouped`/`stacked`/`horizontal`), `radius` |
| `line` | `LineChart` + `Line` | `curve`, `dot`, `stroke_width` |
| `area` | `AreaChart` + `Area` | `stacked`, `gradient`, `curve` |
| `pie` | `PieChart` + `Pie` | `name_key`/`value_key`, `label` |
| `donut` | `PieChart` + `Pie` | as `pie`, plus `inner_radius`, `center_label` |
| `radar` | `RadarChart` + `Radar` | `axis_key`, `fill_opacity` |
| `radial` | `RadialBarChart` + `RadialBar` | `value_key`, `background_track`, `center_total` |

## bar

- `variant` is `grouped` (default), `stacked`, or `horizontal`.
- `radius` rounds the bar corners (`[r,r,0,0]`, or `[0,r,r,0]` when horizontal).
- Each series gets `fill="var(--chart-N)"`; name series explicitly to control
  order and labels.

```json
{
  "chart": "bar", "variant": "stacked",
  "data": [{"m": "Jan", "a": 3, "b": 2}],
  "x": {"key": "m"},
  "series": [{"key": "a", "label": "A"}, {"key": "b", "label": "B"}]
}
```

## line

- `curve` selects the interpolation: `linear`, `monotone` (default),
  `stepAfter`, `step`, `basis`, `natural`.
- `dot: true` draws points; the default is a clean stroke-only line.

## area

- `stacked: true` stacks series; `gradient: true` (default) fills with a
  `<linearGradient>` from 0.8 to 0.1 opacity of `--chart-N`.
- Set `gradient: false` for a flat translucent fill.

## pie / donut

- Name slices with `name_key` + `value_key`, or use a single series over `x.key`.
- `stroke` is `var(--background)` with a 2px stroke and a small padding angle, so
  slices read cleanly on the card.
- `donut: true` (or `chart: "donut"`) cuts an inner radius; `center_label` puts
  text such as `"$12.4k"` in the middle.
- `label: true` draws slice labels and leader lines.

## radar

- `axis_key` names the angle field (defaults to `x.key`).
- Each series is a filled polygon at `fill_opacity` (default `0.6`) over
  `PolarGrid stroke="var(--border)"`.

## radial

- Named progress values render as concentric arcs with `cornerRadius={10}` and a
  muted background track (`background_track: true`).
- `center_total: true` sums the values into the center of the rings.

## Gallery variant knobs

The renderer covers the static variants of the shadcn/ui chart gallery
(`ui.shadcn.com/charts`). These optional spec keys select them:

| Key | Families | Effect |
|---|---|---|
| `curve` | area, line | `linear`, `monotone`, `step` (also `stepAfter`, `basis`, `natural`) |
| `expand` | area, bar | Percentage stacking; the value axis reads 0–100%. Set with `stacked: true`. |
| `axes` | area, bar, line | Show the value axis (same as `y.hide: false`). |
| `labels` | area, bar, line, pie | Bar/line value labels, or pie slice labels. `label` is an alias. |
| `separator` | pie, donut | `false` removes the background-colored slice stroke. |
| `legend_values` | pie, donut | Legend shows each slice's value. |
| `active` | bar, pie, donut | 0-based index highlighted; other slices/bars dim, pie pops out the slice. |
| `negative` | bar | Colors values below zero with `negative_color` (default `--chart-2`). |
| `radar_grid` | radar | `polygon` (default), `circle`, or `none`. |
| `radar_grid_fill` | radar | Tint the polar grid with `--border` at 22%. |
| `radar_dots` | radar | Mark each vertex with a dot. |
| `fill` | radar, area | `false` gives an outline-only radar (`lines-only`). |
| `outer_radius` | radar, pie, donut | Outer radius as a percent string or pixels. |
| `pie_stacked` | pie, donut, radial | Two concentric rings; pair with `value_key_2`. |
| `radial_grid` | radial | Draw a circular polar grid behind the arcs. |
| `radial_labels` | radial | Inside labels on each arc. |
| `radial_corner` | radial | Arc corner radius (default `10`). |
| `radial_stacked` | radial | One ring per named series. |
| `center_label` | donut, radial | Text in the middle (radial also accepts `center_total: true`). |

Examples:

```json
{ "chart": "area", "curve": "step", "gradient": true }
```

```json
{ "chart": "area", "stacked": true, "expand": true, "axes": true }
```

```json
{ "chart": "pie", "pie_stacked": true, "value_key": "amount", "value_key_2": "previous" }
```

Interactive-only gallery entries (the entire Tooltip group and the
`-interactive` charts, which use a live Select) are not rendered as static PNGs.
A few entries that depend on lucide icons or bespoke shapes are approximated with
the closest static styling.

## Common Recharts props

The emitted tree matches the shadcn registry:

- `CartesianGrid vertical={false} stroke="var(--border)"`.
- `XAxis tickLine={false} axisLine={false} tickMargin={8}` with ticks in
  `var(--muted-foreground)`; `YAxis` hidden unless `y.hide === false`.
- Series fill/stroke use `var(--chart-N)` (or your explicit color).
- `isAnimationActive={false}` on every series, for deterministic screenshots.

## Extracted JSX

`render.py component --spec F` prints the equivalent source:

```jsx
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";

const data = [ ... ];
const config = { ... };

export function Chart() {
  return (
    <ChartContainer config={config} className="h-[...px] w-[...px]">
      <BarChart accessibilityLayer data={data} margin={{ top: 4, right: 10, bottom: 4, left: 4 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis dataKey="month" tickLine={false} axisLine={false} tickMargin={8} tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} />
        <YAxis tickLine={false} axisLine={false} tickMargin={8} tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} />
        <Bar dataKey="desktop" fill="var(--chart-1)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ChartContainer>
  );
}
```
