#!/usr/bin/env python3
"""Turn a validated chart spec into a self-contained HTML page and JSX.

``build_html`` writes the shadcn token `<style>`, the chart chrome (title,
description, legend) as HTML, a ``#chart-root`` element sized to the requested
pixels, and a `<script>` that loads the esbuild bundle. ``build_payload`` is the
normalized object handed to the browser; ``build_component`` emits the
equivalent shadcn/Recharts JSX for people who want the source.

This module is not an entry point and imports only the standard library plus
``_lib``.
"""
from __future__ import annotations

import base64
import html
import json
import mimetypes
import os
import string
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import _lib


# ---------------------------------------------------------------------------
# Spec normalization
# ---------------------------------------------------------------------------

def _legend_mode(spec: Dict[str, Any]) -> str:
    legend = spec.get("legend", "bottom")
    if legend is True:
        return "bottom"
    if legend is False:
        return "none"
    if legend in (None, ""):
        return "bottom"
    return str(legend)


def _series_label(entry: Dict[str, Any]) -> str:
    return str(entry.get("label") or entry.get("key") or "")


def _font_stack(spec: Dict[str, Any], base_dir: Optional[Path]) -> Tuple[str, Optional[Dict[str, str]]]:
    """Return ``(css_family, embed)``; embed is an ``@font-face`` payload."""
    font = spec.get("font") or "system"
    if not isinstance(font, str) or font.strip().lower() in ("", "system", "sans", "sans-serif"):
        return _lib.FONT_STACK, None
    candidate = Path(os.path.expanduser(font))
    if not candidate.is_absolute() and base_dir is not None:
        candidate = Path(base_dir) / candidate
    if not candidate.is_file():
        return _lib.FONT_STACK, None
    mime = mimetypes.guess_type(str(candidate))[0] or "font/ttf"
    encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
    return '"ChartFont", ' + _lib.FONT_STACK, {
        "family": "ChartFont",
        "mime": mime,
        "data": encoded,
        "source": str(candidate),
    }


def _layout(spec: Dict[str, Any], has_legend: bool) -> Dict[str, int]:
    width = int(spec["width"])
    height = int(spec["height"])
    pad = int(spec.get("padding", 16))
    legend = _legend_mode(spec)
    title = str(spec.get("title") or "")
    description = str(spec.get("description") or "")
    head = 0
    if title:
        head += 20
    if description:
        head += 20
    if head:
        head += 10
    legend_h = 26 if has_legend and legend in ("top", "bottom") else 0
    legend_w = 116 if has_legend and legend == "right" else 0
    plot_w = max(40, width - 2 * pad - legend_w)
    plot_h = max(40, height - 2 * pad - head - legend_h)
    return {
        "width": width,
        "height": height,
        "padding": pad,
        "plot_width": plot_w,
        "plot_height": plot_h,
        "header_height": head,
        "legend_height": legend_h,
        "legend_width": legend_w,
    }


def build_payload(spec: Dict[str, Any], base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Normalize a validated spec into the object the browser bundle reads."""
    family = spec["chart"]
    palette = _lib.resolve_palette(spec.get("palette"))
    rows: List[Dict[str, Any]] = []
    series_payload: List[Dict[str, Any]] = []
    x_key = ""
    pie_payload: List[Dict[str, Any]] = []
    radar_payload: Dict[str, Any] = {}

    if family in _lib.CARTESIAN_FAMILIES or family == "radar":
        rows, series, x_key = _lib.resolve_rows_and_series(spec)
        if family == "radar":
            axis_key = spec.get("axis_key") or x_key
            if axis_key != x_key:
                for row in rows:
                    if axis_key not in row:
                        raise _lib.CommandError(
                            "invalid_spec", "radar axis key %r is not present in 'data'" % axis_key
                        )
                    row["axis"] = row[axis_key]
            else:
                for row in rows:
                    row["axis"] = row[x_key]
            radar_payload = {
                "axes": rows,
                "series": [],
            }
        series_payload = [
            {"key": entry["key"], "label": _series_label(entry), "color": _lib._series_color(index, entry)}
            for index, entry in enumerate(series)
        ]
        if family == "radar":
            radar_payload["series"] = series_payload
    else:
        slices = _lib.resolve_pie_slices(spec)
        pie_payload = [
            {
                "name": str(slice["name"]),
                "value": slice["value"],
                "value2": slice.get("value2"),
                "color": "var(--chart-%d)" % ((index % 5) + 1),
            }
            for index, slice in enumerate(slices)
        ]

    has_legend = bool(series_payload or pie_payload)
    layout = _layout(spec, has_legend)
    legend = _legend_mode(spec) if has_legend else "none"
    x_spec = spec.get("x") if isinstance(spec.get("x"), dict) else {}
    y_spec = spec.get("y") if isinstance(spec.get("y"), dict) else {}
    variant = spec.get("variant") or ("stacked" if spec.get("stacked") else "grouped")
    horizontal = variant == "horizontal" or bool(spec.get("horizontal"))
    stacked = variant == "stacked" or bool(spec.get("stacked"))
    donut = family == "donut" or bool(spec.get("donut"))
    center_label = None
    if donut and spec.get("center_label"):
        center_label = str(spec["center_label"])
    elif family == "radial" and spec.get("center_label"):
        center_label = str(spec["center_label"])
    elif family == "radial" and spec.get("center_total"):
        center_label = _format_total(sum(float(s["value"]) for s in pie_payload))

    # Horizontal bars put category labels on the y-axis; size that axis from the
    # longest label so long names are not clipped by the card's overflow.
    axis_width = 0
    if family in _lib.CARTESIAN_FAMILIES and horizontal and rows:
        longest = max((len(str(row.get(x_key, ""))) for row in rows), default=0)
        axis_width = max(56, min(240, longest * 7 + 20))
    layout["category_axis_width"] = axis_width

    return {
        "family": family,
        "variant": variant,
        "stacked": stacked,
        "horizontal": horizontal,
        "curve": spec.get("curve") or "monotone",
        "radius": int(spec.get("radius", 4)),
        "gradient": spec.get("gradient", True),
        "donut": donut,
        "inner_radius": spec.get("inner_radius", "55%" if donut else 0),
        "outer_radius": spec.get("outer_radius", "80%"),
        "fill_opacity": float(spec.get("fill_opacity", 0.6)),
        "stroke_width": float(spec.get("stroke_width", 2)),
        "dot": bool(spec.get("dot", False)),
        "grid": bool(spec.get("grid", True)),
        "tooltip": bool(spec.get("tooltip", False)),
        "label": bool(spec.get("label", False)),
        "center_label": center_label,
        "background_track": spec.get("background_track", True),
        "layout": layout,
        "axis_width": axis_width,
        "x": {
            "key": x_key,
            "tick_margin": x_spec.get("tick_margin", 8),
            "hide": bool(x_spec.get("hide", False)),
        },
        "y": {
            "label": y_spec.get("label") or "",
            "domain": y_spec.get("domain"),
            "format": y_spec.get("format") or "raw",
            "hide": y_spec.get("hide", True) is not False,
        },
        "series": series_payload,
        "rows": rows,
        "pie": pie_payload,
        "radial": pie_payload,
        "radar": radar_payload,
        "legend": legend,
        "legend_values": bool(spec.get("legend_values")),
        "expand": bool(spec.get("expand", False)),
        "axes": bool(spec.get("axes", False)),
        "labels": bool(spec.get("labels") or spec.get("label")),
        "separator": spec.get("separator", True) is not False,
        "active_index": int(spec["active"]) if spec.get("active") is not None else None,
        "negative": any(
            isinstance(row.get(entry["key"]), (int, float))
            and not isinstance(row.get(entry["key"]), bool)
            and row.get(entry["key"]) < 0
            for row in rows
            for entry in series_payload
        ),
        "negative_color": spec.get("negative_color") or "var(--chart-2)",
        "radar_grid": spec.get("radar_grid") or ("polygon" if spec.get("grid", True) else "none"),
        "radar_grid_fill": bool(spec.get("radar_grid_fill", False)),
        "radar_dots": bool(spec.get("radar_dots", False)),
        "fill": spec.get("fill", True) is not False,
        "outer_radius": spec.get("outer_radius"),
        "pie_stacked": bool(spec.get("pie_stacked", False)),
        "radial_grid": bool(spec.get("radial_grid", False)),
        "radial_labels": bool(spec.get("radial_labels", False)),
        "radial_stacked": bool(spec.get("radial_stacked", False)),
        "radial_corner": int(spec.get("radial_corner", 10)),
        "palette": palette,
        "theme": spec.get("theme") or "light",
    }


def _format_total(value: float) -> str:
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def _swatch(color: str) -> str:
    return '<span class="legend-swatch" style="background:%s"></span>' % html.escape(color, quote=True)


def _legend_items(payload: Dict[str, Any]) -> List[Tuple[str, str]]:
    if payload["series"]:
        return [(entry["color"], entry["label"]) for entry in payload["series"]]
    items: List[Tuple[str, str]] = []
    for entry in payload["pie"]:
        label = entry["name"]
        if payload.get("legend_values") and entry.get("value") is not None:
            label = "%s — %s" % (label, _format_total(entry["value"]))
        items.append((entry["color"], label))
    return items


def _legend_html(payload: Dict[str, Any], position: str) -> str:
    items = _legend_items(payload)
    if not items or payload["legend"] == "none":
        return ""
    spans = "".join(
        '<span class="legend-item">%s<span>%s</span></span>' % (_swatch(color), html.escape(label))
        for color, label in items
    )
    return '<div class="chart-legend %s">%s</div>' % (position, spans)


def _header_html(payload: Dict[str, Any], spec: Dict[str, Any]) -> str:
    title = spec.get("title")
    description = spec.get("description")
    if not title and not description:
        return ""
    parts = ['<header class="chart-header">']
    if title:
        parts.append('<h1 class="chart-title">%s</h1>' % html.escape(str(title)))
    if description:
        parts.append('<p class="chart-desc">%s</p>' % html.escape(str(description)))
    parts.append("</header>")
    return "".join(parts)


def _center_overlay(payload: Dict[str, Any]) -> str:
    if not payload.get("center_label"):
        return ""
    return '<div class="chart-center">%s</div>' % html.escape(str(payload["center_label"]))


_TEMPLATE_DIR = Path(__file__).resolve().parent
_TEMPLATE_CACHE: Dict[str, str] = {}


def _template(name: str) -> str:
    if name not in _TEMPLATE_CACHE:
        _TEMPLATE_CACHE[name] = (_TEMPLATE_DIR / name).read_text(encoding="utf-8")
    return _TEMPLATE_CACHE[name]


def _render_template(name: str, values: Dict[str, Any]) -> str:
    return string.Template(_template(name)).substitute(values)


def build_html(
    spec: Dict[str, Any],
    bundle_path: Optional[Path] = None,
    *,
    base_dir: Optional[Path] = None,
    transparent: bool = False,
) -> str:
    payload = build_payload(spec, base_dir)
    spec = dict(spec)
    spec.setdefault("grid", True)
    tokens = _lib.theme_tokens(payload["theme"], payload["palette"])
    font_family, embed = _font_stack(spec, base_dir)
    background = spec.get("background", "transparent")
    if transparent or not background or background == "transparent":
        root_background = "transparent"
    else:
        root_background = str(background)
    card = spec.get("card", True)
    legend = payload["legend"]

    token_css = "\n".join("  %s: %s;" % (name, value) for name, value in tokens.items())
    font_face = ""
    if embed:
        font_face = (
            "@font-face { font-family: 'ChartFont'; src: url(data:%s;base64,%s); "
            "font-display: block; }" % (embed["mime"], embed["data"])
        )

    css = _render_template(
        "_chart.css",
        {
            "tokens": token_css,
            "font_family": font_family,
            "font_face": font_face,
            "width": payload["layout"]["width"],
            "height": payload["layout"]["height"],
            "padding": payload["layout"]["padding"],
            "background": root_background,
            "card_border": "border: 1px solid var(--border); border-radius: var(--radius);" if card else "",
            "plot_width": payload["layout"]["plot_width"],
            "plot_height": payload["layout"]["plot_height"],
        },
    )

    header = _header_html(payload, spec)
    overlay = _center_overlay(payload)
    plot = '<div class="chart-plot"><div id="chart-svg"></div>%s</div>' % overlay
    if legend == "top":
        main = '<div class="chart-main column">%s%s</div>' % (_legend_html(payload, "top"), plot)
    elif legend == "right":
        main = '<div class="chart-main row">%s%s</div>' % (plot, _legend_html(payload, "right"))
    elif legend == "bottom":
        main = '<div class="chart-main column">%s%s</div>' % (plot, _legend_html(payload, "bottom"))
    else:
        main = '<div class="chart-main column">%s</div>' % plot

    script_src = ""
    if bundle_path is not None:
        script_src = '<script src="%s"></script>' % Path(bundle_path).resolve().as_uri()

    return _render_template(
        "_chart.html",
        {
            "title": html.escape(str(spec.get("title") or "chart")),
            "css": css,
            "header": header,
            "main": main,
            "root_class": "chart-grid-fill" if payload.get("radar_grid_fill") else "",
            "payload_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
            "script_src": script_src,
        },
    )


# ---------------------------------------------------------------------------
# JSX component extraction
# ---------------------------------------------------------------------------

_FAMILY_IMPORTS = {
    "bar": ["Bar", "BarChart", "CartesianGrid", "XAxis", "YAxis"],
    "line": ["CartesianGrid", "Line", "LineChart", "XAxis", "YAxis"],
    "area": ["Area", "AreaChart", "CartesianGrid", "XAxis", "YAxis"],
    "pie": ["Cell", "Pie", "PieChart"],
    "donut": ["Cell", "Pie", "PieChart"],
    "radar": ["PolarAngleAxis", "PolarGrid", "PolarRadiusAxis", "Radar", "RadarChart"],
    "radial": ["Cell", "RadialBar", "RadialBarChart"],
}


def _jsx_ticks():
    return 'tickLine={false} axisLine={false} tickMargin={8} tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}'


def _jsx_series(payload: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for entry in payload["series"]:
        key = entry["key"]
        color = entry["color"]
        if payload["family"] == "bar":
            radius = "[0, 4, 4, 0]" if payload["horizontal"] else "[4, 4, 0, 0]"
            stack = ' stackId="stack"' if payload["stacked"] else ""
            lines.append('        <Bar dataKey="%s" fill="%s" radius={%s}%s isAnimationActive={false} />' % (key, color, radius, stack))
        elif payload["family"] == "line":
            lines.append(
                '        <Line type="%s" dataKey="%s" stroke="%s" strokeWidth={2} dot={false} isAnimationActive={false} />'
                % (payload["curve"], key, color)
            )
        else:
            lines.append(
                '        <Area type="%s" dataKey="%s" stroke="%s" fill="%s" strokeWidth={2} isAnimationActive={false} />'
                % (payload["curve"], key, color, color)
            )
    return lines


def build_component(spec: Dict[str, Any], base_dir: Optional[Path] = None) -> str:
    """Emit the equivalent shadcn/Recharts JSX for a spec."""
    payload = build_payload(spec, base_dir)
    family = payload["family"]
    imports = _FAMILY_IMPORTS[family]
    data = payload["radar"]["axes"] if family == "radar" else (payload["rows"] or payload["pie"])
    config = {
        entry["key"] if family not in _lib.PIE_FAMILIES else str(entry["name"]): {
            "label": entry.get("label", entry.get("name")),
            "color": entry["color"],
        }
        for entry in (payload["series"] or payload["pie"])
    }
    lines: List[str] = [
        '// Extracted from a charting spec. ChartContainer comes from "@/components/ui/chart".',
        'import { %s } from "recharts";' % ", ".join(imports),
        'import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";',
        "",
        "const data = %s;" % json.dumps(data, indent=2, ensure_ascii=False),
        "",
        "const config = %s;" % json.dumps(config, indent=2, ensure_ascii=False).replace("'", '"'),
        "",
        "export function Chart() {",
        "  return (",
        '    <ChartContainer config={config} className="h-[%dpx] w-[%dpx]">' % (payload["layout"]["plot_height"], payload["layout"]["plot_width"]),
    ]
    if family in _lib.CARTESIAN_FAMILIES:
        chart = {"bar": "BarChart", "line": "LineChart", "area": "AreaChart"}[family]
        layout = ' layout="vertical"' if payload["horizontal"] else ""
        lines.append("      <%s accessibilityLayer%s data={data} margin={{ top: 4, right: 10, bottom: 4, left: 4 }}>" % (chart, layout))
        lines.append("        <CartesianGrid vertical={false} stroke=\"var(--border)\" />")
        lines.append('        <XAxis dataKey="%s" %s />' % (payload["x"]["key"], _jsx_ticks()))
        lines.append("        <YAxis %s />" % _jsx_ticks())
        lines.extend(_jsx_series(payload))
        lines.append("        <ChartTooltip content={<ChartTooltipContent />} />")
        lines.append("      </%s>" % chart)
    elif family in _lib.PIE_FAMILIES:
        inner = "55" if payload["donut"] else "0"
        lines.append('      <PieChart>')
        lines.append(
            '        <Pie data={data} dataKey="value" nameKey="name" innerRadius="%s%%" outerRadius="80%%" '
            'stroke="var(--background)" strokeWidth={2} isAnimationActive={false}>'
            % inner
        )
        lines.append("          {data.map((entry) => (")
        lines.append('            <Cell key={entry.name} fill="%s" />' % "var(--chart-1)")
        lines.append("          ))}")
        lines.append("        </Pie>")
        lines.append("        <ChartTooltip content={<ChartTooltipContent />} />")
        lines.append("      </PieChart>")
    elif family == "radar":
        lines.append('      <RadarChart data={data}>')
        lines.append('        <PolarGrid stroke="var(--border)" />')
        lines.append('        <PolarAngleAxis dataKey="axis" tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} />')
        lines.append("        <PolarRadiusAxis tick={false} axisLine={false} />")
        for entry in payload["series"]:
            lines.append(
                '        <Radar dataKey="%s" stroke="%s" fill="%s" fillOpacity={0.6} isAnimationActive={false} />'
                % (entry["key"], entry["color"], entry["color"])
            )
        lines.append("        <ChartTooltip content={<ChartTooltipContent />} />")
        lines.append("      </RadarChart>")
    else:
        lines.append('      <RadialBarChart data={data} startAngle={90} endAngle={-270}>')
        lines.append('        <RadialBar dataKey="value" cornerRadius={10} background={{ fill: "var(--muted)" }} isAnimationActive={false} />')
        lines.append("      </RadialBarChart>")
    lines.append("    </ChartContainer>")
    lines.append("  );")
    lines.append("}")
    return "\n".join(lines) + "\n"
