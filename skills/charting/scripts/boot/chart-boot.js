/**
 * chart-boot.js — render one normalized chart spec into the page.
 *
 * The Python side (`_html.py`) normalizes a chart spec into `window.__CHART_SPEC__`
 * and this module turns that plain object into a Recharts element tree. It is
 * bundled by esbuild together with React and Recharts (see `build.mjs`) into
 * `vendor/chart-bundle.js`, which the generated HTML loads from disk. Rendering
 * is synchronous and animation-free so a screenshot is deterministic.
 *
 * The knobs mirror the shadcn/ui chart gallery: curve types (linear, step,
 * monotone), percentage "expand" stacking, axis/legend toggles, bar and line
 * value labels, negative/active bars, pie separators/active slices/stacked
 * rings, radar grid shapes and lines-only mode, and radial grids/labels/rings.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Line,
  LineChart,
  Pie,
  PieChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  RadialBar,
  RadialBarChart,
  Sector,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const spec = window.__CHART_SPEC__ || {};
const layout = spec.layout || {};
const width = layout.plot_width || 480;
const height = layout.plot_height || 320;
const margin = { top: 6, right: 12, bottom: 4, left: 4 };
const tickFill = "var(--muted-foreground)";
const tickStyle = { fill: tickFill, fontSize: 12 };
const h = React.createElement;

function formatValue(format) {
  if (format === "percent") {
    return (value) => `${Math.round(value)}%`;
  }
  if (format === "expand") {
    return (value) => `${Math.round(value * 100)}%`;
  }
  if (format === "currency") {
    return (value) =>
      `$${Number(value).toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
  }
  if (format === "compact") {
    return (value) => new Intl.NumberFormat("en-US", { notation: "compact" }).format(value);
  }
  if (format === "number") {
    return (value) => Number(value).toLocaleString("en-US");
  }
  return undefined;
}

function gridElement() {
  if (!spec.grid) {
    return null;
  }
  return h(CartesianGrid, { key: "grid", vertical: false, stroke: "var(--border)" });
}

function showYAxis() {
  return spec.axes === true || (spec.y && spec.y.hide === false);
}

function xAxis(dataKey) {
  return h(XAxis, {
    key: "x",
    dataKey,
    tickLine: false,
    axisLine: false,
    tickMargin: spec.x && spec.x.tick_margin != null ? spec.x.tick_margin : 8,
    tick: tickStyle,
    interval: "preserveStartEnd",
  });
}

function yAxis() {
  if (!showYAxis()) {
    return null;
  }
  return h(YAxis, {
    key: "y",
    tickLine: false,
    axisLine: false,
    width: 46,
    tick: tickStyle,
    domain: spec.expand ? [0, 1] : spec.y && spec.y.domain ? spec.y.domain : undefined,
    tickFormatter: formatValue(spec.expand ? "expand" : spec.y && spec.y.format),
  });
}

function barCells(series) {
  const active = spec.active_index;
  const negatives = spec.negative === true;
  if (active == null && !negatives) {
    return null;
  }
  return (spec.rows || []).map((row, index) => {
    let fill = series.color;
    let opacity = 1;
    if (negatives && Number(row[series.key]) < 0) {
      fill = spec.negative_color || "var(--chart-2)";
    }
    if (active != null) {
      opacity = index === active ? 1 : 0.35;
    }
    return h(Cell, { key: index, fill, fillOpacity: opacity });
  });
}

function labelsFor(key, position) {
  if (spec.labels !== true) {
    return null;
  }
  return h(LabelList, {
    key: "labels",
    dataKey: key,
    position: position || "top",
    fill: "var(--muted-foreground)",
    fontSize: 11,
    formatter: formatValue(spec.y && spec.y.format),
  });
}

function seriesChildren() {
  const defs = [];
  const series = [];
  (spec.series || []).forEach((entry, index) => {
    const fill = entry.color;
    const stackId = spec.stacked || spec.expand ? "stack" : undefined;
    if (spec.family === "bar") {
      const barRadius = spec.horizontal
        ? [0, spec.radius, spec.radius, 0]
        : [spec.radius, spec.radius, 0, 0];
      series.push(
        h(
          Bar,
          {
            key: entry.key,
            dataKey: entry.key,
            name: entry.label,
            fill,
            radius: barRadius,
            stackId,
            isAnimationActive: false,
          },
          [barCells(entry), labelsFor(entry.key, spec.horizontal ? "right" : "top")]
        )
      );
      return;
    }
    if (spec.family === "line") {
      series.push(
        h(
          Line,
          {
            key: entry.key,
            type: spec.curve || "monotone",
            dataKey: entry.key,
            name: entry.label,
            stroke: fill,
            strokeWidth: spec.stroke_width || 2,
            dot: spec.dot === true ? { r: 3, strokeWidth: 0, fill } : false,
            activeDot: false,
            connectNulls: true,
            isAnimationActive: false,
            fill: "none",
          },
          [labelsFor(entry.key, "top")]
        )
      );
      return;
    }
    const gradientId = `fill-${index}-${entry.key}`;
    defs.push(
      h(
        "linearGradient",
        { key: gradientId, id: gradientId, x1: "0", y1: "0", x2: "0", y2: "1" },
        h("stop", { offset: "5%", stopColor: fill, stopOpacity: 0.8 }),
        h("stop", { offset: "95%", stopColor: fill, stopOpacity: 0.1 })
      )
    );
    series.push(
      h(
        Area,
        {
          key: entry.key,
          type: spec.curve || "monotone",
          dataKey: entry.key,
          name: entry.label,
          stroke: fill,
          strokeWidth: spec.stroke_width || 2,
          fill: spec.gradient === false ? fill : `url(#${gradientId})`,
          fillOpacity: spec.gradient === false ? 0.4 : 1,
          stackId,
          isAnimationActive: false,
        },
        [labelsFor(entry.key, "top")]
      )
    );
  });
  if (defs.length) {
    series.unshift(h("defs", { key: "defs" }, defs));
  }
  return series;
}

function cartesianChart() {
  const Chart = { bar: BarChart, line: LineChart, area: AreaChart }[spec.family];
  const children = [gridElement()];
  if (spec.horizontal === true) {
    children.push(
      h(XAxis, {
        key: "xv",
        type: "number",
        tickLine: false,
        axisLine: false,
        tick: tickStyle,
        tickFormatter: formatValue(spec.expand ? "expand" : spec.y && spec.y.format),
        hide: !showYAxis(),
      })
    );
    children.push(
      h(YAxis, {
        key: "yc",
        type: "category",
        dataKey: spec.x.key,
        tickLine: false,
        axisLine: false,
        width: spec.axis_width || 64,
        tick: tickStyle,
        interval: 0,
      })
    );
  } else {
    children.push(xAxis(spec.x.key));
    children.push(yAxis());
  }
  children.push(...seriesChildren());
  if (spec.tooltip) {
    children.push(h(Tooltip, { key: "tooltip", cursor: false, isAnimationActive: false }));
  }
  return h(
    Chart,
    {
      width,
      height,
      data: spec.rows || [],
      margin,
      layout: spec.horizontal ? "vertical" : "horizontal",
      stackOffset: spec.expand ? "expand" : "none",
    },
    children
  );
}

function pieCells(seriesColor) {
  const active = spec.active_index;
  return (spec.pie || []).map((slice, index) =>
    h(Cell, {
      key: slice.name,
      fill: active != null ? (index === active ? "var(--chart-1)" : seriesColor) : slice.color,
      fillOpacity: active != null && index !== active ? 0.45 : 1,
      stroke: spec.separator === false ? "none" : "var(--background)",
    })
  );
}

function activeSlice(props) {
  return h(Sector, { ...props, outerRadius: (props.outerRadius || 0) + 8 });
}

function pieChart() {
  const multiple = spec.pie_stacked === true;
  const pies = [];
  const outer = h(
    Pie,
    {
      key: "outer",
      data: spec.pie || [],
      dataKey: "value",
      nameKey: "name",
      cx: "50%",
      cy: "50%",
      innerRadius: multiple ? "62%" : spec.donut ? spec.inner_radius : 0,
      outerRadius: spec.outer_radius || "78%",
      paddingAngle: 2,
      stroke: spec.separator === false ? "none" : "var(--background)",
      strokeWidth: spec.separator === false ? 0 : 2,
      label: spec.labels === true,
      labelLine: spec.labels === true,
      activeIndex: spec.active_index != null ? spec.active_index : undefined,
      activeShape: spec.active_index != null ? activeSlice : undefined,
      isAnimationActive: false,
    },
    pieCells("var(--chart-3)")
  );
  pies.push(outer);
  if (multiple) {
    pies.push(
      h(
        Pie,
        {
          key: "inner",
          data: spec.pie || [],
          dataKey: "value2",
          nameKey: "name",
          cx: "50%",
          cy: "50%",
          innerRadius: "32%",
          outerRadius: "56%",
          paddingAngle: 2,
          stroke: "var(--background)",
          strokeWidth: 2,
          isAnimationActive: false,
        },
        (spec.pie || []).map((slice) =>
          h(Cell, { key: slice.name, fill: slice.color, fillOpacity: 0.55 })
        )
      )
    );
  }
  return h(PieChart, { width, height, margin }, pies);
}

function radarGrid() {
  if (spec.radar_grid === "none") {
    return null;
  }
  const type = spec.radar_grid === "circle" ? "circle" : "polygon";
  const props = { key: "pgrid", gridType: type, stroke: "var(--border)", fill: "none" };
  if (spec.radar_grid_fill) {
    props.fill = "var(--border)";
    props.fillOpacity = 0.2;
  }
  return h(PolarGrid, props);
}

function radarChart() {
  const axes = spec.radar && spec.radar.axes ? spec.radar.axes : [];
  const series = spec.radar && spec.radar.series ? spec.radar.series : [];
  const children = [
    radarGrid(),
    h(PolarAngleAxis, { key: "angle", dataKey: "axis", tick: tickStyle }),
  ];
  if (spec.radar_grid !== "circle") {
    children.push(h(PolarRadiusAxis, { key: "radius", angle: 90, tick: false, axisLine: false }));
  }
  series.forEach((entry) => {
    children.push(
      h(Radar, {
        key: entry.key,
        dataKey: entry.key,
        name: entry.label,
        stroke: entry.color,
        fill: entry.color,
        fillOpacity: spec.fill === false ? 0 : spec.fill_opacity != null ? spec.fill_opacity : 0.6,
        dot: spec.radar_dots === true ? { r: 3, fillOpacity: 1 } : false,
        isAnimationActive: false,
      })
    );
  });
  return h(
    RadarChart,
    { width, height, data: axes, margin, outerRadius: spec.outer_radius || "72%" },
    children
  );
}

function radialChart() {
  const children = [];
  if (spec.radial_grid) {
    children.push(h(PolarGrid, { key: "pgrid", gridType: "circle", stroke: "var(--border)" }));
  }
  const background = spec.background_track === false ? undefined : { fill: "var(--muted)" };
  let bars;
  if (spec.pie_stacked) {
    bars = [
      { key: "value", color: "var(--chart-1)", opacity: 1, background },
      { key: "value2", color: "var(--chart-2)", opacity: 0.6, background: undefined },
    ];
  } else if (spec.radial_stacked && spec.radar && spec.radar.series && spec.radar.series.length) {
    bars = spec.radar.series.map((entry) => ({ key: entry.key, color: entry.color, background }));
  } else {
    bars = [{ key: "value", color: "var(--chart-1)", background }];
  }
  bars.forEach((entry, index) => {
    children.push(
      h(
        RadialBar,
        {
          key: entry.key || `bar-${index}`,
          dataKey: entry.key,
          data: spec.radial || [],
          cornerRadius: spec.radial_corner != null ? spec.radial_corner : 10,
          background: entry.background,
          fill: entry.color,
          label: spec.radial_labels
            ? { position: "insideStart", fill: "var(--background)", fontSize: 11 }
            : false,
          isAnimationActive: false,
        },
        (spec.radial || []).map((slice) =>
          h(Cell, { key: slice.name, fill: entry.color, fillOpacity: entry.opacity })
        )
      )
    );
  });
  return h(
    RadialBarChart,
    { width, height, data: spec.radial || [], margin, startAngle: 90, endAngle: -270 },
    children
  );
}

function pickChart() {
  if (spec.family === "bar" || spec.family === "line" || spec.family === "area") {
    return cartesianChart();
  }
  if (spec.family === "pie" || spec.family === "donut") {
    return pieChart();
  }
  if (spec.family === "radar") {
    return radarChart();
  }
  if (spec.family === "radial") {
    return radialChart();
  }
  return h("div", { style: { color: "var(--foreground)", font: "14px sans-serif" } }, `Unknown chart family: ${spec.family}`);
}

function mount() {
  const target = document.getElementById("chart-svg") || document.getElementById("chart-root");
  if (!target) {
    window.__chartReady = true;
    return;
  }
  const root = createRoot(target);
  root.render(pickChart());
  window.__chartReady = true;
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mount);
} else {
  mount();
}
