#!/usr/bin/env python3
"""Media, layout, and structural block builders for pdf-creator.

``BlocksB`` covers images, figures, code, callouts, quotes, rules, spacers,
page breaks and templates, multi-column blocks, tables of contents, checkbox
and definition lists, key/value grids, anchors, QR/barcode blocks, and the
cover page. Mixed into ``Builder`` in ``_engine.py``.
"""
from __future__ import annotations

import io
from typing import Any, Dict, List

import _lib
from _rl import rl


class BlocksB:
    """Image, figure, code, callout, quote, rule, layout, and cover blocks."""

    # -- media --------------------------------------------------------------

    def _block_image(self, block: Dict[str, Any]) -> List[Any]:
        rlr = rl()
        data, intrinsic = self._image_reader(block.get("src"))
        width, height = self._image_size(block, intrinsic)
        image = rlr.Image(io.BytesIO(data), width=width, height=height)
        image.hAlign = {"center": "CENTER", "centre": "CENTER", "right": "RIGHT"}.get(
            str(block.get("align", "center")).lower(), "CENTER"
        )
        flowables: List[Any] = []
        border = block.get("border")
        if border:
            if isinstance(border, dict):
                thickness = _lib.parse_length(border.get("width", 0.5), self.unit, field="border") or 0.5
                border_color = self._color(border.get("color", "@border"))
                pad = _lib.parse_length(border.get("padding", "2mm"), self.unit, field="border padding") or 0
                background = self._color(border.get("background", "white"))
            else:
                thickness = 0.5
                border_color = self._color("@border")
                pad = _lib.parse_length("2mm", self.unit) or 0
                background = self._color("white")
            wrapper = rlr.Table([[image]], colWidths=[width + 2 * pad])
            wrapper.setStyle(rlr.TableStyle([
                ("BOX", (0, 0), (-1, -1), thickness, border_color),
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("LEFTPADDING", (0, 0), (-1, -1), pad),
                ("RIGHTPADDING", (0, 0), (-1, -1), pad),
                ("TOPPADDING", (0, 0), (-1, -1), pad),
                ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]))
            wrapper.hAlign = image.hAlign
            flowables.append(wrapper)
        else:
            flowables.append(image)
        caption = block.get("caption")
        if caption:
            text = str(caption)
            if _lib.parse_bool(block.get("numbered"), False):
                self.figure_seq += 1
                text = "Figure %d. %s" % (self.figure_seq, text)
            flowables.append(self._paragraph(self._markup(block, text), self.style("caption")))
        return flowables

    def _block_figure(self, block: Dict[str, Any]) -> List[Any]:
        image_block = dict(block.get("image") or {})
        if not image_block:
            image_block = {
                key: block[key]
                for key in ("src", "width", "height", "max_width", "max_height", "align", "border")
                if key in block
            }
        image_block["numbered"] = False
        result = self._block_image(image_block)
        caption = block.get("caption")
        if caption:
            text = str(caption)
            if _lib.parse_bool(block.get("number"), True):
                self.figure_seq += 1
                text = "Figure %d. %s" % (self.figure_seq, text)
            result.append(self._paragraph(self._markup(block, text), self.style("caption")))
        return result

    # -- code / callout / quote --------------------------------------------

    def _block_code(self, block: Dict[str, Any]) -> List[Any]:
        rlr = rl()
        text = str(block.get("text", ""))
        if _lib.parse_bool(block.get("line_numbers"), False):
            lines = text.split("\n")
            width = len(str(len(lines)))
            text = "\n".join(("%*d  %s" % (width, i + 1, line)).rstrip() for i, line in enumerate(lines))
        style = self.style("code", block.get("style") if isinstance(block.get("style"), dict) else None)
        body: Any
        if _lib.parse_bool(block.get("wrap"), True):
            body = rlr.XPreformatted(text, style)
        else:
            body = rlr.Preformatted(text, style)
        background = self._color(block.get("background", "@code_bg"))
        padding = _lib.parse_length(block.get("padding", "3.4mm"), self.unit, field="padding") or 0
        cell_content: List[Any] = []
        if block.get("language"):
            cell_content.append(
                self._paragraph(
                    _lib.escape_xml(str(block["language"])),
                    self.style("code", {"font_size": 7.5, "color": "@muted"}),
                )
            )
        cell_content.append(body)
        wrapper = rlr.Table([[cell_content]], colWidths=[self.frame_width])
        commands: List[Any] = [
            ("BACKGROUND", (0, 0), (-1, -1), background),
            ("LEFTPADDING", (0, 0), (-1, -1), padding),
            ("RIGHTPADDING", (0, 0), (-1, -1), padding),
            ("TOPPADDING", (0, 0), (-1, -1), padding),
            ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
        ]
        border = block.get("border_color")
        if border:
            commands.append(("BOX", (0, 0), (-1, -1), 0.4, self._color(border)))
        wrapper.setStyle(rlr.TableStyle(commands))
        wrapper.hAlign = "LEFT"
        return [wrapper]

    _CALLOUT_KINDS = {
        "info": ("info", "info_soft"),
        "note": ("info", "info_soft"),
        "success": ("success", "success_soft"),
        "tip": ("success", "success_soft"),
        "warning": ("warning", "warning_soft"),
        "warn": ("warning", "warning_soft"),
        "danger": ("danger", "danger_soft"),
        "error": ("danger", "danger_soft"),
    }

    def _block_callout(self, block: Dict[str, Any]) -> List[Any]:
        rlr = rl()
        kind = str(block.get("kind", "info")).lower()
        accent_key, soft_key = self._CALLOUT_KINDS.get(kind, ("info", "info_soft"))
        accent = self._color(block.get("accent", "@%s" % accent_key))
        background = self._color(block.get("background", "@%s" % soft_key))
        content: List[Any] = []
        if block.get("title"):
            content.append(
                self._paragraph(self._markup(block, block["title"]), self.style("callout_title", {"color": accent}))
            )
        content.append(self._paragraph(self._markup(block, block.get("text", "")), self.style("callout_body")))
        padding = _lib.parse_length(block.get("padding", "3.5mm"), self.unit, field="padding") or 0
        table = rlr.Table([[content]], colWidths=[self.frame_width])
        table.setStyle(rlr.TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), background),
            ("LINEBEFORE", (0, 0), (0, -1), 3, accent),
            ("BOX", (0, 0), (-1, -1), 0.4, background),
            ("LEFTPADDING", (0, 0), (-1, -1), padding),
            ("RIGHTPADDING", (0, 0), (-1, -1), padding),
            ("TOPPADDING", (0, 0), (-1, -1), padding),
            ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
        ]))
        table.hAlign = "LEFT"
        return [table]

    def _block_blockquote(self, block: Dict[str, Any]) -> List[Any]:
        rlr = rl()
        content: List[Any] = [
            self._paragraph(self._markup(block, block.get("text", "")), self.style("quote", {"left_indent": 0}))
        ]
        if block.get("attribution"):
            content.append(
                self._paragraph(
                    "\u2014 %s" % self._markup(block, block["attribution"]),
                    self.style("small", {"align": "right"}),
                )
            )
        accent = self._color(block.get("accent", "@accent"))
        table = rlr.Table([[content]], colWidths=[self.frame_width])
        table.setStyle(rlr.TableStyle([
            ("LINEBEFORE", (0, 0), (0, -1), 2.5, accent),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        table.hAlign = "LEFT"
        return [table]

    # -- rules / spacing / page control ------------------------------------

    def _block_divider(self, block: Dict[str, Any]) -> List[Any]:
        rlr = rl()
        width = _lib.parse_length(
            block.get("width", "100%"), self.unit, base=self.frame_width, allow_percent=True, field="divider width"
        )
        thickness = _lib.parse_length(block.get("thickness", 0.6), self.unit, field="thickness") or 0.6
        color = self._color(block.get("color", "@border"))
        line_style = str(block.get("line_style", "solid")).lower()
        dash = {"dashed": [3, 2], "dotted": [1, 2]}.get(line_style)
        return [
            rlr.HRFlowable(
                width=width or self.frame_width,
                thickness=thickness,
                color=color,
                dash=dash,
                spaceBefore=_lib.parse_length(block.get("space_before", "2mm"), self.unit) or 0,
                spaceAfter=_lib.parse_length(block.get("space_after", "3mm"), self.unit) or 0,
            )
        ]

    _block_hr = _block_divider

    def _block_spacer(self, block: Dict[str, Any]) -> List[Any]:
        rlr = rl()
        height = _lib.parse_length(block.get("height", "6mm"), self.unit, field="spacer height") or 0
        return [rlr.Spacer(1, height)]

    def _block_page_break(self, block: Dict[str, Any]) -> List[Any]:
        rlr = rl()
        flowables: List[Any] = []
        template = block.get("template")
        if template:
            if template not in _lib.PAGE_TEMPLATES:
                raise _lib.CommandError("invalid_spec", "unknown page template %r" % template)
            flowables.append(rlr.NextPageTemplate(template))
        flowables.append(rlr.PageBreak())
        return flowables

    def _block_page_template(self, block: Dict[str, Any]) -> List[Any]:
        rlr = rl()
        name = str(block.get("name") or "body")
        if name not in _lib.PAGE_TEMPLATES:
            raise _lib.CommandError("invalid_spec", "unknown page template %r" % name)
        if str(block.get("break", "before")).lower() == "none":
            return [rlr.NextPageTemplate(name)]
        return [rlr.NextPageTemplate(name), rlr.PageBreak()]

    def _block_columns(self, block: Dict[str, Any]) -> List[Any]:
        rlr = rl()
        explicit = block.get("columns")
        if isinstance(explicit, list) and explicit and all(isinstance(c, list) for c in explicit):
            column_contents = explicit
        else:
            count = max(1, int(block.get("count", 2)))
            flat = block.get("content") or []
            column_contents = [[] for _ in range(count)]
            for index, item in enumerate(flat):
                column_contents[index % count].append(item)
        count = len(column_contents)
        gap = _lib.parse_length(block.get("gap", "6mm"), self.unit, field="columns gap") or 0.0
        col_width = (self.frame_width - gap * (count - 1)) / count
        cells = [self._as_flowables(column) for column in column_contents]
        table = rlr.Table([cells], colWidths=[col_width] * count)
        commands: List[Any] = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-2, -1), gap),
            ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]
        table.setStyle(rlr.TableStyle(commands))
        table.hAlign = "LEFT"
        if block.get("keep_together"):
            return [rlr.KeepTogether([table])]
        return [table]

    # -- contents and lists -------------------------------------------------

    def _make_toc(self, config: Dict[str, Any]) -> Any:
        rlr = rl()
        toc = rlr.TableOfContents()
        depth = max(1, int(config.get("depth", 3)))
        toc.levelStyles = [self.style("toc%d" % (i + 1)) for i in range(depth)]
        toc.dotsMinLevel = 0 if _lib.parse_bool(config.get("dot_leader"), True) else depth
        return toc

    def _block_toc(self, block: Dict[str, Any]) -> List[Any]:
        rlr = rl()
        self.has_toc = True
        flowables: List[Any] = []
        title = block.get("title")
        if title:
            flowables.append(self._paragraph(self._markup(block, title), self.style("toc_title")))
        flowables.append(self._make_toc(block))
        if _lib.parse_bool(block.get("page_break"), True):
            flowables.append(rlr.PageBreak())
        return flowables

    def _block_checkbox_list(self, block: Dict[str, Any]) -> List[Any]:
        rlr = rl()
        rows: List[List[Any]] = []
        for item in block.get("items") or []:
            if isinstance(item, dict):
                checked = _lib.parse_bool(item.get("checked"), False)
                text = item.get("text", "")
            else:
                checked, text = False, item
            mark = "[x]" if checked else "[ ]"
            rows.append([
                self._paragraph("%s  %s" % (mark, self._markup(block, text)), self.style("body", {"space_after": 3}))
            ])
        if not rows:
            return []
        table = rlr.Table(rows, colWidths=[self.frame_width])
        table.setStyle(rlr.TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        table.hAlign = "LEFT"
        return [table]

    def _block_definition_list(self, block: Dict[str, Any]) -> List[Any]:
        flowables: List[Any] = []
        for item in block.get("items") or []:
            if not isinstance(item, dict):
                continue
            flowables.append(
                self._paragraph(self._markup(item, item.get("term", "")), self.style("definition_term"))
            )
            flowables.append(
                self._paragraph(self._markup(item, item.get("definition", "")), self.style("definition_body"))
            )
        return flowables

    def _block_key_values(self, block: Dict[str, Any]) -> List[Any]:
        rlr = rl()
        pairs = []
        for item in block.get("items") or []:
            if isinstance(item, dict):
                pairs.append((item.get("key", ""), item.get("value", "")))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                pairs.append((item[0], item[1]))
        per_row = max(1, int(block.get("columns", 1)))
        rows: List[List[Any]] = []
        row: List[Any] = []
        for key, value in pairs:
            row.append(self._paragraph(self._markup(block, key), self.style("key")))
            row.append(self._paragraph(self._markup(block, value), self.style("value")))
            if len(row) // 2 >= per_row:
                rows.append(row)
                row = []
        if row:
            while len(row) < per_row * 2:
                row.append(self._paragraph("", self.style("value")))
            rows.append(row)
        if not rows:
            return []
        unit_width = self.frame_width / per_row
        key_ratio = float(block.get("key_ratio", 0.35))
        value_ratio = float(block.get("value_ratio", 0.65))
        col_widths = [unit_width * (key_ratio if i % 2 == 0 else value_ratio) for i in range(per_row * 2)]
        table = rlr.Table(rows, colWidths=col_widths)
        table.setStyle(rlr.TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        table.hAlign = "LEFT"
        return [table]

    # -- anchors and codes --------------------------------------------------

    def _block_anchor(self, block: Dict[str, Any]) -> List[Any]:
        self.anchor_seq += 1
        name = str(block.get("name") or "anchor-%d" % self.anchor_seq)
        return [
            self._paragraph(
                '<a name="%s"/>' % name,
                self.style("small", {"font_size": 0.1, "leading": 0.1, "space_after": 0}),
            )
        ]

    def _block_qr(self, block: Dict[str, Any]) -> List[Any]:
        rlr = rl()
        if rlr.qr is None:
            self.warnings.append("QR blocks need the reportlab barcode module; skipped")
            return []
        from reportlab.graphics.shapes import Drawing

        size = _lib.parse_length(block.get("size", "30mm"), self.unit, field="qr size") or 85
        widget = rlr.qr.QrCodeWidget(str(block.get("data", "")))
        x0, y0, x1, y1 = widget.getBounds()
        scale_x = size / max(1.0, x1 - x0)
        scale_y = size / max(1.0, y1 - y0)
        drawing = Drawing(size, size, transform=[scale_x, 0, 0, scale_y, -x0 * scale_x, -y0 * scale_y])
        drawing.add(widget)
        drawing.hAlign = {"center": "CENTER", "centre": "CENTER", "right": "RIGHT"}.get(
            str(block.get("align", "center")).lower(), "CENTER"
        )
        flowables: List[Any] = [drawing]
        if block.get("caption"):
            flowables.append(self._paragraph(self._markup(block, block["caption"]), self.style("caption")))
        return flowables

    _BARCODE_ALIASES = {
        "code128": "Code128",
        "code128auto": "Code128Auto",
        "code39": "Standard39",
        "standard39": "Standard39",
        "extended39": "Extended39",
        "code93": "Standard93",
        "extended93": "Extended93",
        "ean13": "EAN13",
        "ean8": "EAN8",
        "ean5": "EAN5",
        "upca": "UPCA",
        "upc": "UPCA",
        "i2of5": "I2of5",
        "itf": "I2of5",
        "codabar": "Codabar",
        "postnet": "POSTNET",
        "isbn": "ISBN",
        "msi": "MSI",
        "code11": "Code11",
    }

    def _block_barcode(self, block: Dict[str, Any]) -> List[Any]:
        rlr = rl()
        if rlr.createBarcodeDrawing is None:
            self.warnings.append("barcode blocks need the reportlab barcode module; skipped")
            return []
        requested = str(block.get("kind", "code128"))
        kind = self._BARCODE_ALIASES.get(requested.lower().replace("-", "").replace("_", ""), requested)
        width = _lib.parse_length(block.get("width", "60mm"), self.unit, field="barcode width") or 170
        height = _lib.parse_length(block.get("height", "15mm"), self.unit, field="barcode height") or 40
        try:
            drawing = rlr.createBarcodeDrawing(
                kind,
                value=str(block.get("data", "")),
                width=width,
                height=height,
                humanReadable=_lib.parse_bool(block.get("human_readable"), True),
            )
        except Exception as exc:
            self.warnings.append("could not build %s barcode: %s" % (kind, exc))
            return []
        drawing.hAlign = {"center": "CENTER", "centre": "CENTER", "right": "RIGHT"}.get(
            str(block.get("align", "center")).lower(), "CENTER"
        )
        flowables: List[Any] = [drawing]
        if block.get("caption"):
            flowables.append(self._paragraph(self._markup(block, block["caption"]), self.style("caption")))
        return flowables

    # -- cover --------------------------------------------------------------

    def _cover_flowables(self, cover: Any) -> List[Any]:
        rlr = rl()
        if isinstance(cover, str):
            cover = {"title": cover}
        cover = dict(cover or {})
        out: List[Any] = []
        top_space = _lib.parse_length(cover.get("top_space", "42mm"), self.unit, field="top_space") or 0
        out.append(rlr.Spacer(1, top_space))
        if cover.get("logo") or cover.get("image"):
            image_block = {
                "src": cover.get("logo") or cover.get("image"),
                "align": cover.get("logo_align", "left"),
                "max_height": cover.get("logo_max_height", "22mm"),
            }
            out.extend(self._block_image(image_block))
            out.append(rlr.Spacer(1, _lib.parse_length(cover.get("logo_space", "10mm"), self.unit) or 0))
        if cover.get("eyebrow"):
            out.append(
                self._paragraph(
                    self._markup({}, cover["eyebrow"]),
                    self.style("small", {"color": "@accent", "align": cover.get("align", "left")}),
                )
            )
        if cover.get("title"):
            out.append(
                self._paragraph(
                    self._markup({}, cover["title"]),
                    self.style("title", {"font_size": cover.get("title_size", 30), "align": cover.get("align", "left")}),
                )
            )
        if cover.get("subtitle"):
            out.append(
                self._paragraph(
                    self._markup({}, cover["subtitle"]),
                    self.style("subtitle", {"align": cover.get("align", "left")}),
                )
            )
        if cover.get("rule"):
            out.append(rlr.HRFlowable(
                width=self.frame_width,
                thickness=1.2,
                color=self._color("@accent"),
                spaceBefore=6,
                spaceAfter=10,
            ))
        if cover.get("author"):
            out.append(
                self._paragraph(
                    self._markup({}, cover["author"]),
                    self.style("body", {"align": cover.get("align", "left")}),
                )
            )
        if cover.get("date"):
            out.append(
                self._paragraph(
                    self._markup({}, cover["date"]),
                    self.style("small", {"align": cover.get("align", "left")}),
                )
            )
        if cover.get("abstract"):
            out.append(rlr.Spacer(1, _lib.parse_length(cover.get("abstract_space", "14mm"), self.unit) or 0))
            out.append(
                self._paragraph(
                    self._markup({}, cover["abstract"]),
                    self.style("lead", {"align": cover.get("abstract_align", "left")}),
                )
            )
        if cover.get("footer"):
            out.append(rlr.Spacer(1, _lib.parse_length(cover.get("footer_space", "20mm"), self.unit) or 0))
            out.append(
                self._paragraph(
                    self._markup({}, cover["footer"]),
                    self.style("small", {"align": cover.get("footer_align", "left")}),
                )
            )
        return out
