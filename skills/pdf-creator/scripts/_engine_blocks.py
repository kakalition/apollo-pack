#!/usr/bin/env python3
"""Content-block builders for the pdf-creator rendering engine.

``BlocksA`` covers text and data blocks: headings, paragraphs, inline rich
text, lists, and tables. It is mixed into ``Builder`` in ``_engine.py``; the
methods rely on the state and helpers that ``Builder`` sets up and are not
usable on their own.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import _lib
from _rl import rl


class BlocksA:
    """Heading, paragraph, rich text, list, and table blocks."""

    # -- heading / paragraph / rich ----------------------------------------

    def _block_heading(self, block: Dict[str, Any]) -> List[Any]:
        level = int(block.get("level", 1))
        level = max(1, min(level, 6))
        text = self._markup(block, block.get("text", ""))
        number = block.get("number")
        prefix = ""
        if number is True or (number is None and self.number_headings):
            prefix = self._heading_number(level) + "  "
        elif isinstance(number, (str, int)) and not isinstance(number, bool):
            prefix = str(number) + "  "
        self.anchor_seq += 1
        key = str(block.get("anchor") or "sec-%d" % self.anchor_seq)
        plain = _lib.plain_text(prefix + text)
        para = self._paragraph(
            '<a name="%s"/>%s%s' % (key, prefix, text),
            self.block_style(block, "h%d" % level),
        )
        para._toc_level = level
        para._toc_text = plain
        para._toc_key = key
        return [para]

    def _block_paragraph(self, block: Dict[str, Any]) -> List[Any]:
        markup = self._markup(block, block.get("text", ""))
        return [self._paragraph(markup, self.block_style(block, "body"))]

    def _block_rich(self, block: Dict[str, Any]) -> List[Any]:
        spans = block.get("spans") or []
        if not isinstance(spans, list):
            raise _lib.CommandError("invalid_spec", "'rich' spans must be a list")
        parts: List[str] = []
        for span in spans:
            if isinstance(span, str):
                parts.append(_lib.escape_xml(span))
                continue
            if not isinstance(span, dict):
                continue
            text = _lib.escape_xml(span.get("text", ""))
            if span.get("code"):
                text = '<font name="%s">%s</font>' % (self.mono_family, text)
            if span.get("link"):
                text = '<link href="%s">%s</link>' % (span["link"], text)
            if span.get("font") or span.get("size") or span.get("color"):
                attrs = ""
                if span.get("font"):
                    attrs += ' face="%s"' % self._resolve_font(span["font"])
                if span.get("size"):
                    attrs += ' size="%s"' % span["size"]
                if span.get("color"):
                    r, g, b, _ = _lib.parse_color(span["color"])
                    attrs += ' color="#%02X%02X%02X"' % (int(r * 255), int(g * 255), int(b * 255))
                text = "<font%s>%s</font>" % (attrs, text)
            if span.get("bold"):
                text = "<b>%s</b>" % text
            if span.get("italic"):
                text = "<i>%s</i>" % text
            if span.get("underline"):
                text = "<u>%s</u>" % text
            if span.get("strike"):
                text = "<strike>%s</strike>" % text
            if span.get("super"):
                text = "<super>%s</super>" % text
            if span.get("sub"):
                text = "<sub>%s</sub>" % text
            parts.append(text)
        markup = "".join(parts).replace("\n", "<br/>")
        return [self._paragraph(markup, self.block_style(block, "body"))]

    # -- lists --------------------------------------------------------------

    def _list_flowable(
        self,
        items: Any,
        *,
        ordered: bool,
        start: int = 1,
        bullet: Optional[str] = None,
        style_name: str = "body",
    ) -> Any:
        rlr = rl()
        style = self.style(style_name)
        flowables: List[Any] = []
        for item in items:
            if isinstance(item, dict):
                text = self._markup(item, item.get("text", ""))
                children = item.get("items") or item.get("content")
                nested = None
                if children:
                    nested = self._list_flowable(
                        children,
                        ordered=_lib.parse_bool(item.get("ordered"), ordered),
                        start=int(item.get("start", 1)),
                        bullet=item.get("bullet"),
                        style_name=style_name,
                    )
                para = self._paragraph(text, self.style(style_name, {"space_after": 1}))
                content = [para, nested] if nested is not None else para
                flowables.append(rlr.ListItem(content))
            else:
                text = self._markup({}, item)
                flowables.append(
                    rlr.ListItem(self._paragraph(text, self.style(style_name, {"space_after": 1})))
                )
        if ordered:
            return rlr.ListFlowable(
                flowables,
                bulletType="1",
                start=str(start),
                leftIndent=style.leftIndent + 14,
                bulletFontName=style.fontName,
                bulletFontSize=style.fontSize,
                bulletDedent=12,
            )
        return rlr.ListFlowable(
            flowables,
            bulletType="bullet",
            start=bullet or "\u2022",
            leftIndent=style.leftIndent + 14,
            bulletFontName=style.fontName,
            bulletFontSize=style.fontSize,
            bulletDedent=12,
        )

    def _block_list(self, block: Dict[str, Any]) -> List[Any]:
        items = block.get("items") or block.get("content") or []
        if not isinstance(items, list):
            raise _lib.CommandError("invalid_spec", "'list' items must be a list")
        style_name = block.get("style") if isinstance(block.get("style"), str) else "body"
        return [
            self._list_flowable(
                items,
                ordered=_lib.parse_bool(block.get("ordered"), False),
                start=int(block.get("start", 1)),
                bullet=block.get("bullet"),
                style_name=style_name,
            )
        ]

    # -- tables -------------------------------------------------------------

    def _cell_flowable(self, value: Any, *, header: bool, default_align: str = "left") -> Any:
        style_name = "table_header" if header else "table_cell"
        if isinstance(value, dict):
            overrides: Dict[str, Any] = value.get("style") if isinstance(value.get("style"), dict) else {}
            if value.get("align"):
                overrides = dict(overrides, align=value["align"])
            if value.get("color"):
                overrides = dict(overrides, color=value["color"])
            if value.get("bold") and "font_family" not in overrides:
                overrides["font_family"] = self._family_variant("bold")
            if value.get("size"):
                overrides = dict(overrides, font_size=value["size"])
            if value.get("background"):
                overrides = dict(overrides, back_color=value["background"])
            style = self.style(style_name, overrides) if overrides else self.style(style_name)
            text = value.get("text", "")
        else:
            style = self.style(style_name)
            text = value
        if isinstance(text, list):
            return self._as_flowables(text)
        numeric = isinstance(text, (int, float)) and not isinstance(text, bool)
        looks_numeric = isinstance(text, str) and bool(re.match(r"^\s*[+-]?[\d.,]+\s*%?\s*$", text))
        if default_align == "auto" and (numeric or looks_numeric):
            style = self.style(style_name, {"align": "right"})
        return self._paragraph(self._markup(value if isinstance(value, dict) else {}, text), style)

    def _block_table(self, block: Dict[str, Any]) -> List[Any]:
        rlr = rl()
        header = block.get("header")
        rows = block.get("rows")
        if rows is not None:
            data = list(rows)
        elif block.get("data") is not None:
            data = list(block["data"])
            header = None
        else:
            raise _lib.CommandError("invalid_spec", "'table' needs 'rows' or 'data'")
        header_row: Optional[List[Any]] = None
        if header:
            if not isinstance(header, list):
                raise _lib.CommandError("invalid_spec", "'table.header' must be a list")
            header_row = list(header)
        number_align = str(block.get("number_align", "auto")).lower()

        matrix: List[List[Any]] = []
        for row in data:
            if not isinstance(row, (list, tuple)):
                raise _lib.CommandError("invalid_spec", "each table row must be a list")
            if number_align == "first":
                matrix.append([
                    self._cell_flowable(cell, header=False, default_align="right" if index > 0 else "left")
                    for index, cell in enumerate(row)
                ])
            else:
                matrix.append([
                    self._cell_flowable(cell, header=False, default_align=number_align) for cell in row
                ])
        table_data: List[List[Any]] = []
        if header_row is not None:
            table_data.append([self._cell_flowable(cell, header=True) for cell in header_row])
        table_data.extend(matrix)
        if not table_data:
            return []

        column_count = max(len(row) for row in table_data)
        for row in table_data:
            while len(row) < column_count:
                row.append(self._paragraph("", self.style("table_cell")))

        col_widths = self._column_widths(block, column_count)
        row_heights = None
        if block.get("row_heights"):
            row_heights = [
                _lib.parse_length(v, self.unit, field="row height") for v in block["row_heights"]
            ]
        repeat = int(block.get("repeat_header", 1)) if header_row is not None else 0
        table = rlr.Table(
            table_data,
            colWidths=col_widths,
            rowHeights=row_heights,
            repeatRows=repeat,
            hAlign=self._h_align(block.get("align")),
        )
        table.setStyle(self._table_style(block, table_data, header_row is not None))
        flowables: List[Any] = []
        caption_top = block.get("caption") and str(block.get("caption_position", "bottom")).lower() == "top"
        if caption_top:
            flowables.append(self._table_caption(block))
        if block.get("keep_together"):
            flowables.append(rlr.KeepTogether([table]))
        else:
            flowables.append(table)
        if block.get("caption") and not caption_top:
            flowables.append(self._table_caption(block))
        if block.get("space_after"):
            flowables.append(
                rlr.Spacer(1, _lib.parse_length(block["space_after"], self.unit, field="space_after") or 0)
            )
        return flowables

    def _table_caption(self, block: Dict[str, Any]) -> Any:
        caption = str(block["caption"])
        if _lib.parse_bool(block.get("numbered"), False):
            self.table_seq += 1
            caption = "Table %d. %s" % (self.table_seq, caption)
        return self._paragraph(self._markup(block, caption), self.style("table_caption"))

    def _column_widths(self, block: Dict[str, Any], count: int) -> Optional[List[float]]:
        raw = block.get("col_widths") or block.get("widths")
        if not raw:
            return None
        if not isinstance(raw, (list, tuple)) or len(raw) != count:
            self.warnings.append(
                "table widths length does not match %d columns; using auto widths" % count
            )
            return None
        numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in raw)
        if numeric:
            total = float(sum(raw))
            if total <= 1.0001:
                return [float(v) * self.frame_width for v in raw]
            return [float(v) for v in raw]
        return [
            _lib.parse_length(v, self.unit, base=self.frame_width, allow_percent=True, field="column width") or 0.0
            for v in raw
        ]

    def _h_align(self, value: Any) -> str:
        return {"center": "CENTER", "centre": "CENTER", "right": "RIGHT", "left": "LEFT"}.get(
            str(value or "").lower(), "LEFT"
        )

    def _table_style(self, block: Dict[str, Any], table_data: List[List[Any]], has_header: bool) -> Any:
        rlr = rl()
        grid_value = block.get("grid", block.get("style", "modern"))
        if isinstance(grid_value, bool):
            preset = "grid" if grid_value else "none"
        else:
            preset = str(grid_value or "modern").lower()
        if preset in ("lines", "line", "hairline", "modern"):
            preset = "modern"

        border_color = self._color(block.get("border_color", "@border"))
        hairline = self._color(block.get("row_line_color", "@border"))
        border_width = _lib.parse_length(block.get("border_width", 0.4), self.unit, field="border_width") or 0.4
        padding = _lib.parse_length(block.get("padding", "3.2mm"), self.unit, field="padding") or 0
        cell_style = self.style("table_cell")
        header_style = self.style("table_header")
        zebra = _lib.parse_bool(block.get("zebra"), preset == "zebra")
        header_bg = self._color(
            block.get("header_background", "@surface" if preset == "modern" else "@header_bg")
        )

        commands: List[Any] = [
            ("FONTNAME", (0, 0), (-1, -1), cell_style.fontName),
            ("FONTSIZE", (0, 0), (-1, -1), cell_style.fontSize),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0 if preset == "modern" else padding),
            ("RIGHTPADDING", (0, 0), (-1, -1), padding),
            ("TOPPADDING", (0, 0), (-1, -1), padding),
            ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
        ]
        if preset == "grid":
            commands.append(("GRID", (0, 0), (-1, -1), border_width, border_color))
        elif preset == "box":
            commands.append(("BOX", (0, 0), (-1, -1), border_width, border_color))
        elif preset == "modern":
            # Hairline rules only: one under the header, faint ones between rows.
            if has_header and len(table_data) > 1:
                commands.append(("LINEBELOW", (0, 0), (-1, 0), 0.8, border_color))
            for index in range(1, len(table_data) - 1):
                commands.append(("LINEBELOW", (0, index), (-1, index), 0.3, hairline))
        elif preset == "lines":
            commands.append(("BOX", (0, 0), (-1, -1), border_width, border_color))
            if len(table_data) > 1:
                commands.append(("LINEBELOW", (0, 0), (-1, -2), 0.4, border_color))
        if has_header:
            commands.extend([
                ("BACKGROUND", (0, 0), (-1, 0), header_bg),
                ("TEXTCOLOR", (0, 0), (-1, 0), self._color(block.get("header_color", "@text" if preset == "modern" else "@header_text"))),
                ("FONTNAME", (0, 0), (-1, 0), header_style.fontName),
                ("FONTSIZE", (0, 0), (-1, 0), header_style.fontSize),
                ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
            ])
        if zebra:
            start = 1 if has_header else 0
            zebra_color = self._color(block.get("zebra_color", "@zebra"))
            for index in range(start, len(table_data)):
                if (index - start) % 2 == 1:
                    commands.append(("BACKGROUND", (0, index), (-1, index), zebra_color))
        for span in block.get("spans") or []:
            try:
                c0, r0, c1, r1 = [int(v) for v in span]
                commands.append(("SPAN", (c0, r0), (c1, r1)))
            except (TypeError, ValueError):
                self.warnings.append("ignored malformed table span %r" % (span,))
        for row in block.get("row_backgrounds") or []:
            try:
                index, color = int(row[0]), row[1]
                commands.append(("BACKGROUND", (0, index), (-1, index), self._color(color)))
            except (TypeError, ValueError, IndexError):
                self.warnings.append("ignored malformed row background %r" % (row,))
        for styled in block.get("cell_styles") or []:
            try:
                col, row = int(styled["col"]), int(styled["row"])
                color = styled.get("background") or styled.get("color")
                key = "BACKGROUND" if styled.get("background") else "TEXTCOLOR"
                if color:
                    commands.append((key, (col, row), (col, row), self._color(color)))
            except (TypeError, ValueError, KeyError):
                self.warnings.append("ignored malformed cell style %r" % (styled,))
        return rlr.TableStyle(commands)
