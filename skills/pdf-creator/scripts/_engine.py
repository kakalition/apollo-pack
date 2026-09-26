#!/usr/bin/env python3
"""ReportLab rendering engine for the pdf-creator skill.

Public entry point: :func:`build_pdf`, which turns a validated document spec
(see ``references/schema.md``) into a PDF and returns render statistics. The
module never imports reportlab at load time: the engine is pulled in lazily via
:mod:`_rl`, so every non-rendering verb keeps working without it.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import _lib
from _engine_blocks import BlocksA
from _engine_blocks2 import BlocksB
from _rl import rl
from _themes import ALIGNMENTS, BASE_PALETTE, BASE_STYLE_PROPS, STYLE_ATTRS, THEMES

_NAMED_PAGE_SIZES = (
    "A0", "A1", "A2", "A3", "A4", "A5", "A6",
    "B0", "B1", "B2", "B3", "B4", "B5", "B6",
    "LETTER", "LEGAL", "TABLOID", "LEDGER", "EXECUTIVE", "FOLIO", "QUARTO",
    "STATEMENT", "ELEVENSEVENTEEN",
)

# Friendly family names -> the base Type1 face reportlab expects, plus the
# bold/italic faces used when a family has no registered TTF.
_BASE_FONT_ALIASES = {"Times": "Times-Roman"}
_BUILTIN_FAMILIES: Dict[str, Dict[str, str]] = {
    "Helvetica": {
        "normal": "Helvetica", "bold": "Helvetica-Bold",
        "italic": "Helvetica-Oblique", "bold-italic": "Helvetica-BoldOblique",
    },
    "Times": {
        "normal": "Times-Roman", "bold": "Times-Bold",
        "italic": "Times-Italic", "bold-italic": "Times-BoldItalic",
    },
    "Courier": {
        "normal": "Courier", "bold": "Courier-Bold",
        "italic": "Courier-Oblique", "bold-italic": "Courier-BoldOblique",
    },
}


class Builder(BlocksA, BlocksB):
    """Resolves a spec into styles, geometry, and a flowable story."""

    def __init__(
        self,
        spec: Dict[str, Any],
        *,
        home: Path,
        base_dir: Optional[Path] = None,
        settings: Optional[Dict[str, str]] = None,
        allow_remote: bool = False,
    ) -> None:
        self.rl = rl()
        self.spec = spec
        self.home = Path(home)
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.settings = dict(_lib.SETTING_DEFAULTS)
        if settings:
            self.settings.update({key: value for key, value in settings.items() if value is not None})
        self.allow_remote = allow_remote or _lib.parse_bool(self.settings.get("allow_remote"), False)
        self.warnings: List[str] = []

        self.unit = str(self.settings.get("unit") or "mm")
        self.base_size = self._setting_float("font_size", 10.5)
        self.line_height = self._setting_float("line_height", 1.4)
        self.heading_scale = self._setting_float("heading_scale", 1.0) or 1.0

        self.theme_name, self.theme = self._resolve_theme()
        self.palette = dict(BASE_PALETTE)
        self.palette.update(self.theme.get("palette") or {})
        self.palette.update(self._spec_dict("colors"))
        font_cfg = self._spec_dict("font")
        self.font_family = (
            font_cfg.get("family")
            or self.theme.get("font_family")
            or self.settings.get("font_family")
            or "Helvetica"
        )
        self.mono_family = font_cfg.get("mono") or "Courier"

        self._registered_families: Dict[str, str] = {}
        self._registered_variants: Dict[str, Dict[str, str]] = {}
        self._load_fonts()

        self.number_headings = _lib.parse_bool(
            self.spec.get("number_headings", self.theme.get("number_headings", False)), False
        )
        self.page_break_headings = self._parse_page_break_headings(
            self.spec.get("page_break_headings", self.theme.get("page_break_headings"))
        )
        self.heading_counters: Dict[int, int] = {}
        self.figure_seq = 0
        self.table_seq = 0
        self.anchor_seq = 0
        self._style_props = self._build_style_props()
        self._style_cache: Dict[str, Any] = {}
        self._geometry = self._resolve_geometry()
        self._frames_cache: Dict[str, List[Any]] = {}
        self._furniture_config: Dict[str, Dict[str, Any]] = {}
        self._build_furniture()
        self.has_toc = False

    # -- small helpers ------------------------------------------------------

    def _setting_float(self, key: str, default: float) -> float:
        try:
            return float(str(self.settings.get(key, default)).strip())
        except (TypeError, ValueError):
            return float(default)

    def _spec_dict(self, key: str) -> Dict[str, Any]:
        value = self.spec.get(key)
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _parse_page_break_headings(value: Any) -> set:
        """Normalize ``page_break_headings`` into a set of heading levels.

        Accepts ``true`` (break before every level-1 heading), a single level,
        or a list of levels. Levels outside 1-6 are ignored.
        """
        if value is None or value is False:
            return set()
        if value is True:
            return {1}
        items = value if isinstance(value, (list, tuple, set)) else [value]
        levels = set()
        for item in items:
            try:
                level = int(item)
            except (TypeError, ValueError):
                continue
            if 1 <= level <= 6:
                levels.add(level)
        return levels

    def _heading_starts_page(self, block: Dict[str, Any]) -> bool:
        """True when a heading asks to begin on a fresh page."""
        if _lib.parse_bool(block.get("page_break"), False) or _lib.parse_bool(block.get("break_before"), False):
            return True
        try:
            level = int(block.get("level", 1))
        except (TypeError, ValueError):
            return False
        return level in self.page_break_headings

    def _resolve_theme(self) -> Tuple[str, Dict[str, Any]]:
        theme_spec = self.spec.get("theme")
        name = self.settings.get("theme") or "default"
        overrides: Dict[str, Any] = {}
        if isinstance(theme_spec, str) and theme_spec.strip():
            name = theme_spec.strip()
        elif isinstance(theme_spec, dict):
            name = str(theme_spec.get("name") or name)
            overrides = {key: value for key, value in theme_spec.items() if key != "name"}
        base = _lib.deep_merge(THEMES["default"], THEMES.get(name, {}))
        if name not in THEMES:
            self.warnings.append("unknown theme %r; falling back to 'default'" % name)
            name = "default"
        return name, _lib.deep_merge(base, overrides)

    def _color(self, value: Any, default: Optional[str] = None) -> Any:
        if isinstance(value, self.rl.colors.Color):
            return value
        raw = value
        if isinstance(raw, str) and raw.startswith("@"):
            raw = self.palette.get(raw[1:], default or "#000000")
        if raw is None:
            raw = default if default is not None else self.palette.get("text")
        r, g, b, a = _lib.parse_color(raw)
        return self.rl.colors.Color(r, g, b, alpha=a)

    def _resolve_prop(self, value: Any) -> Any:
        if isinstance(value, str) and value.startswith("@"):
            key = value[1:]
            if key == "family":
                return self.font_family
            if key == "family_bold":
                return self._family_variant("bold")
            if key == "family_italic":
                return self._family_variant("italic")
            if key == "family_bold_italic":
                return self._family_variant("bold-italic")
            if key == "mono":
                return self.mono_family
            return self.palette.get(key, value)
        return value

    def _family_variant(self, variant: str) -> str:
        if self.font_family in self._registered_variants:
            return self._registered_variants[self.font_family].get(variant, self.font_family)
        faces = _BUILTIN_FAMILIES.get(self.font_family)
        if faces:
            return faces.get(variant, faces["normal"])
        return self.font_family

    # -- fonts --------------------------------------------------------------

    def _resolve_font_path(self, value: Any, search: Sequence[str] = ("fonts", "assets")) -> Path:
        if not value:
            raise _lib.CommandError("invalid_spec", "a font entry needs a 'file'")
        candidate = Path(os.path.expanduser(str(value)))
        options: List[Path] = []
        if candidate.is_absolute():
            options.append(candidate)
        else:
            options.append(self.base_dir / candidate)
            for sub in search:
                options.append(self.home / sub / candidate)
            options.append(self.home / candidate)
        for option in options:
            if option.is_file():
                return option
        raise _lib.CommandError("not_found", "font file not found: %s" % value)

    def _register_font_entry(self, entry: Dict[str, Any], origin: str) -> None:
        base_family = str(entry.get("name") or Path(str(entry.get("file") or "font")).stem)
        try:
            self.rl.pdfmetrics.registerFont(self.rl.TTFont(base_family, str(self._resolve_font_path(entry.get("file")))))
            variants = {"bold": base_family, "italic": base_family, "bold-italic": base_family}
            for variant, key in (("bold", "bold"), ("italic", "italic"), ("bold-italic", "bold_italic")):
                if entry.get(key):
                    face_name = "%s-%s" % (base_family, variant)
                    self.rl.pdfmetrics.registerFont(self.rl.TTFont(face_name, str(self._resolve_font_path(entry[key]))))
                    variants[variant] = face_name
                    self._registered_families[face_name] = face_name
            self.rl.registerFontFamily(
                base_family,
                normal=base_family,
                bold=variants["bold"],
                italic=variants["italic"],
                boldItalic=variants["bold-italic"],
            )
            self._registered_families[base_family] = base_family
            self._registered_variants[base_family] = {"normal": base_family, **variants}
            if entry.get("name") and str(entry["name"]) != base_family:
                self._registered_families[str(entry["name"])] = base_family
                self._registered_variants[str(entry["name"])] = {"normal": base_family, **variants}
        except _lib.CommandError:
            raise
        except Exception as exc:
            self.warnings.append("could not register font %r from %s: %s" % (base_family, origin, exc))

    def _load_fonts(self) -> None:
        manifest = self.home / "fonts" / "fonts.json"
        if manifest.is_file():
            try:
                entries = json.loads(manifest.read_text(encoding="utf-8"))
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict):
                            self._register_font_entry(entry, str(manifest))
            except Exception as exc:
                self.warnings.append("could not read font manifest %s: %s" % (manifest, exc))
        for entry in self.spec.get("fonts") or []:
            if isinstance(entry, dict):
                self._register_font_entry(entry, "spec.fonts")

    def _resolve_font(self, family: Optional[str]) -> str:
        if not family:
            family = self.font_family
        if family in self._registered_families:
            return self._registered_families[family]
        if family in _BUILTIN_FAMILIES:
            return _BUILTIN_FAMILIES[family]["normal"]
        if family in _BASE_FONT_ALIASES:
            return _BASE_FONT_ALIASES[family]
        if family in self.rl.pdfmetrics.standardFonts:
            return family
        self.warnings.append("unknown font family %r; using %r" % (family, self.font_family))
        return self._resolve_font(self.font_family)

    # -- styles -------------------------------------------------------------

    def _build_style_props(self) -> Dict[str, Dict[str, Any]]:
        props: Dict[str, Dict[str, Any]] = {}
        for name, base in BASE_STYLE_PROPS.items():
            merged = dict(base)
            if name.startswith("h") and name[1:].isdigit():
                for key in ("font_size", "leading"):
                    if key in merged:
                        merged[key] = float(merged[key]) * self.heading_scale
            props[name] = merged
        for source in (self.theme.get("styles") or {}, self._spec_dict("styles")):
            for name, override in source.items():
                if isinstance(override, dict):
                    props[name] = _lib.deep_merge(props.get(name, {}), override)
        return props

    def _style_kwargs(self, props: Dict[str, Any]) -> Dict[str, Any]:
        resolved = {key: self._resolve_prop(value) for key, value in props.items()}
        size = float(resolved.get("font_size", self.base_size))
        leading = resolved.get("leading")
        if leading is None:
            leading = size * float(resolved.get("line_height", self.line_height))
        kwargs: Dict[str, Any] = {
            "fontName": self._resolve_font(resolved.get("font_family")),
            "fontSize": size,
            "leading": float(leading),
        }
        for key, value in resolved.items():
            attr = STYLE_ATTRS.get(key)
            if not attr:
                continue
            if key == "color":
                kwargs["textColor"] = self._color(value)
            elif key == "align":
                kwargs["alignment"] = getattr(self.rl, ALIGNMENTS.get(str(value).lower(), "TA_LEFT"))
            elif key in ("back_color", "border_color"):
                kwargs[attr] = self._color(value)
            elif key == "bullet_font":
                kwargs[attr] = self._resolve_font(value)
            elif key in ("left_indent", "right_indent", "first_line_indent", "bullet_indent", "border_width", "border_padding", "border_radius", "space_before", "space_after"):
                parsed = _lib.parse_length(value, "pt", field=key)
                if parsed is not None:
                    kwargs[attr] = parsed
            elif key == "bullet_size":
                kwargs[attr] = float(value)
            elif key in ("keep_with_next", "word_wrap", "allow_widows", "allow_orphans", "underline"):
                kwargs[attr] = _lib.parse_bool(value)
            else:
                kwargs[attr] = value
        return kwargs

    def style(self, name: str, overrides: Optional[Dict[str, Any]] = None) -> Any:
        props = dict(self._style_props.get(name, self._style_props["body"]))
        if overrides:
            props = _lib.deep_merge(props, overrides)
            key = "%s~%s" % (name, json.dumps(overrides, sort_keys=True, default=str))
        else:
            key = name
        if key not in self._style_cache:
            self._style_cache[key] = self.rl.ParagraphStyle(key, **self._style_kwargs(props))
        return self._style_cache[key]

    def block_style(self, block: Dict[str, Any], default: str = "body") -> Any:
        declared = block.get("style")
        overrides: Dict[str, Any] = {}
        style_name = default
        if isinstance(declared, str):
            style_name = declared
        elif isinstance(declared, dict):
            overrides.update(declared)
        shorthand = {
            "align": "align", "color": "color", "size": "font_size", "font": "font_family",
            "leading": "leading", "line_height": "line_height", "space_before": "space_before",
            "space_after": "space_after", "indent": "left_indent", "left_indent": "left_indent",
            "first_line_indent": "first_line_indent", "keep_with_next": "keep_with_next",
            "background": "back_color", "back_color": "back_color", "border_color": "border_color",
            "border_width": "border_width", "padding": "border_padding", "border_padding": "border_padding",
        }
        for key, prop in shorthand.items():
            if key in block:
                overrides[prop] = block[key]
        return self.style(style_name, overrides) if overrides else self.style(style_name)

    # -- geometry -----------------------------------------------------------

    def _page_size(self, name: Any) -> Tuple[float, float]:
        if isinstance(name, (list, tuple)) and len(name) == 2:
            return (
                _lib.parse_length(name[0], self.unit, field="page size width") or 0.0,
                _lib.parse_length(name[1], self.unit, field="page size height") or 0.0,
            )
        text = str(name or self.settings.get("page_size") or "A4").strip()
        if "x" in text.lower():
            parts = re.split(r"[xX]", text)
            if len(parts) == 2:
                if not re.search(r"[a-zA-Z]", parts[0]):
                    parts = ["%s%s" % (parts[0], self.unit), "%s%s" % (parts[1], self.unit)]
                return (
                    _lib.parse_length(parts[0], self.unit, field="page width") or 0.0,
                    _lib.parse_length(parts[1], self.unit, field="page height") or 0.0,
                )
        key = text.upper().replace(" ", "")
        if key in _NAMED_PAGE_SIZES and hasattr(self.rl.pagesizes, key):
            width, height = getattr(self.rl.pagesizes, key)
            return float(width), float(height)
        raise _lib.CommandError("invalid_spec", "unknown page size %r" % name)

    def _resolve_geometry(self) -> Dict[str, Any]:
        theme_page = self.theme.get("page") if isinstance(self.theme.get("page"), dict) else {}
        page = _lib.deep_merge(theme_page, self._spec_dict("page"))
        width, height = self._page_size(page.get("size") or self.settings.get("page_size") or "A4")
        orientation = str(page.get("orientation") or self.settings.get("orientation") or "portrait").lower()
        if orientation in ("landscape", "l"):
            if width < height:
                width, height = height, width
        elif orientation in ("portrait", "p"):
            if width > height:
                width, height = height, width
        elif orientation != "auto":
            raise _lib.CommandError("invalid_spec", "orientation must be portrait or landscape")

        margins = page.get("margins")
        top = right = bottom = left = None
        if isinstance(margins, dict):
            horizontal, vertical = margins.get("horizontal"), margins.get("vertical")
            top = margins.get("top", vertical)
            bottom = margins.get("bottom", vertical)
            left = margins.get("left", horizontal)
            right = margins.get("right", horizontal)
        elif margins is not None:
            top = right = bottom = left = margins
        top = top if top is not None else self.settings.get("margin_top", "20mm")
        right = right if right is not None else self.settings.get("margin_right", "18mm")
        bottom = bottom if bottom is not None else self.settings.get("margin_bottom", "20mm")
        left = left if left is not None else self.settings.get("margin_left", "18mm")

        return {
            "size": (width, height),
            "orientation": "landscape" if width > height else "portrait",
            "margins": {
                "top": _lib.parse_length(top, self.unit, field="margin.top") or 0.0,
                "right": _lib.parse_length(right, self.unit, field="margin.right") or 0.0,
                "bottom": _lib.parse_length(bottom, self.unit, field="margin.bottom") or 0.0,
                "left": _lib.parse_length(left, self.unit, field="margin.left") or 0.0,
            },
            "header_reserve": _lib.parse_length(page.get("header_reserve", "10mm"), self.unit, field="header_reserve") or 0.0,
            "footer_reserve": _lib.parse_length(page.get("footer_reserve", "10mm"), self.unit, field="footer_reserve") or 0.0,
            "columns_gap": _lib.parse_length(page.get("columns_gap", "7mm"), self.unit, field="columns_gap") or 0.0,
        }

    @property
    def page_size(self) -> Tuple[float, float]:
        return self._geometry["size"]

    @property
    def frame_width(self) -> float:
        width, _ = self._geometry["size"]
        return width - self._geometry["margins"]["left"] - self._geometry["margins"]["right"]

    @property
    def frame_height(self) -> float:
        _, height = self._geometry["size"]
        return (
            height
            - self._geometry["margins"]["top"]
            - self._geometry["margins"]["bottom"]
            - self._geometry["header_reserve"]
            - self._geometry["footer_reserve"]
        )

    def _build_frames(self, template: str) -> List[Any]:
        if template in self._frames_cache:
            return self._frames_cache[template]

        def frame(x: float, y: float, w: float, h: float, name: str) -> Any:
            return self.rl.Frame(
                x, y, max(1.0, w), max(1.0, h), id=name,
                leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
            )

        width, height = self._geometry["size"]
        margins = dict(self._geometry["margins"])
        if template == "landscape":
            width, height = height, width
            margins = {"top": margins["left"], "right": margins["top"], "bottom": margins["right"], "left": margins["bottom"]}
        content_x = margins["left"]
        content_w = width - margins["left"] - margins["right"]
        content_h = height - margins["top"] - margins["bottom"] - self._geometry["header_reserve"] - self._geometry["footer_reserve"]
        content_y = margins["bottom"] + self._geometry["footer_reserve"]
        if template == "cover":
            content_h = height - margins["top"] - margins["bottom"]
            content_y = margins["bottom"]
            frames = [frame(content_x, content_y, content_w, content_h, "cover-frame")]
        elif template in ("title", "blank"):
            content_h = height - margins["top"] - margins["bottom"]
            content_y = margins["bottom"]
            frames = [frame(content_x, content_y, content_w, content_h, "%s-frame" % template)]
        elif template == "two_column":
            gap = self._geometry["columns_gap"]
            col_w = (content_w - gap) / 2.0
            frames = [
                frame(content_x, content_y, col_w, content_h, "col-1"),
                frame(content_x + col_w + gap, content_y, col_w, content_h, "col-2"),
            ]
        elif template == "three_column":
            gap = self._geometry["columns_gap"]
            col_w = (content_w - 2 * gap) / 3.0
            frames = [
                frame(content_x, content_y, col_w, content_h, "col-1"),
                frame(content_x + col_w + gap, content_y, col_w, content_h, "col-2"),
                frame(content_x + 2 * (col_w + gap), content_y, col_w, content_h, "col-3"),
            ]
        else:
            frames = [frame(content_x, content_y, content_w, content_h, "main")]
        self._frames_cache[template] = frames
        return frames

    def _template_pagesize(self, template: str) -> Tuple[float, float]:
        width, height = self._geometry["size"]
        if template == "landscape":
            return height, width
        return width, height

    def _template_order(self) -> List[str]:
        base = ["body", "two_column", "three_column", "landscape", "title", "blank", "cover"]
        if self.spec.get("cover"):
            base = ["cover", "body", "two_column", "three_column", "landscape", "title", "blank"]
        return base

    # -- furniture (header / footer / watermark) ---------------------------

    def _meta(self) -> Dict[str, Any]:
        meta = self._spec_dict("meta")
        return {
            "title": str(meta.get("title") or ""),
            "author": str(meta.get("author") or self.settings.get("author") or ""),
            "subject": str(meta.get("subject") or ""),
            "keywords": [str(k) for k in (meta.get("keywords") or [])],
            "creator": str(meta.get("creator") or "pdf-creator"),
            "language": str(meta.get("language") or self.settings.get("language") or "en"),
        }

    def _furniture_for(self, template: str) -> Dict[str, Any]:
        def norm(value: Any) -> Optional[Dict[str, Any]]:
            if isinstance(value, str) and value:
                return {"text": value}
            return dict(value) if isinstance(value, dict) else None

        if template in ("cover", "title", "blank"):
            header = norm(self.spec.get("%s_header" % template))
            footer = norm(self.spec.get("%s_footer" % template))
        else:
            header = norm(self.spec.get("header", self.theme.get("header")))
            footer = norm(self.spec.get("footer", self.theme.get("footer")))
        overlay = (self.spec.get("page_templates") or {}).get(template) or {}
        header = norm(overlay.get("header", header))
        footer = norm(overlay.get("footer", footer))
        watermark = overlay.get("watermark", self.spec.get("watermark"))
        if isinstance(watermark, str):
            watermark = {"text": watermark}
        return {
            "template": template,
            "header": header,
            "footer": footer,
            "watermark": watermark if isinstance(watermark, dict) else None,
            "background": overlay.get("background", self.spec.get("background")),
            "page_numbers": _lib.parse_bool(
                overlay.get("page_numbers", self.spec.get("page_numbers")),
                bool(footer and "{page}" in str(footer.get("text", ""))),
            ),
            "margins": self._geometry["margins"],
            "header_reserve": self._geometry["header_reserve"],
            "footer_reserve": self._geometry["footer_reserve"],
            "meta": self._meta(),
        }

    def _build_furniture(self) -> None:
        for template in _lib.PAGE_TEMPLATES:
            self._furniture_config[template] = self._furniture_for(template)

    # -- images -------------------------------------------------------------

    def _read_image_bytes(self, src: Any) -> Tuple[bytes, str]:
        if not src:
            raise _lib.CommandError("invalid_spec", "an image block needs 'src'")
        text = str(src).strip()
        if text.startswith("data:"):
            try:
                header, payload = text.split(",", 1)
                if "base64" not in header:
                    raise ValueError("only base64 data URIs are supported")
                return base64.b64decode(payload), "data-uri"
            except Exception as exc:
                raise _lib.CommandError("invalid_spec", "invalid data URI: %s" % exc)
        if text.lower().startswith(("http://", "https://")):
            if not self.allow_remote:
                raise _lib.CommandError("remote_disabled", "remote images are disabled; pass --allow-remote to fetch %s" % text)
            try:
                with urllib.request.urlopen(text, timeout=30) as response:
                    return response.read(), text
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise _lib.CommandError("io_error", "could not fetch %s: %s" % (text, exc))
        candidate = Path(os.path.expanduser(text))
        options = [candidate] if candidate.is_absolute() else [
            self.base_dir / candidate,
            self.home / "assets" / candidate,
            self.home / candidate,
            Path.cwd() / candidate,
        ]
        for option in options:
            if option.is_file():
                try:
                    return option.read_bytes(), str(option)
                except OSError as exc:
                    raise _lib.CommandError("io_error", "could not read %s: %s" % (option, exc))
        raise _lib.CommandError("not_found", "image not found: %s" % src)

    def _image_reader(self, src: Any) -> Tuple[bytes, Tuple[float, float]]:
        """Return normalized image bytes and intrinsic ``(width, height)``.

        Bytes are returned rather than an ``ImageReader`` because reportlab's
        ``Image`` flowable accepts an image path or a file-like object, not a
        reader instance.
        """
        data, origin = self._read_image_bytes(src)
        try:
            from PIL import Image as PILImage
            from PIL import ImageOps

            pil = ImageOps.exif_transpose(PILImage.open(io.BytesIO(data)))
            image_format = (pil.format or "PNG").upper()
            if image_format in ("JPG", "MPO"):
                image_format = "JPEG"
            if image_format not in ("PNG", "JPEG", "GIF", "BMP", "TIFF"):
                image_format = "PNG"
            if image_format == "JPEG" and pil.mode not in ("RGB", "L"):
                pil = pil.convert("RGB")
            elif image_format == "PNG" and pil.mode == "P":
                pil = pil.convert("RGBA")
            buffer = io.BytesIO()
            pil.save(buffer, format=image_format)
            data = buffer.getvalue()
        except ImportError:
            pass
        except Exception as exc:
            self.warnings.append("Pillow could not preprocess %s: %s" % (origin, exc))
        try:
            reader = self.rl.ImageReader(io.BytesIO(data))
            width, height = reader.getSize()
        except Exception as exc:
            raise _lib.CommandError("invalid_image", "could not read image %s: %s" % (origin, exc))
        return data, (float(width), float(height))

    def _image_size(self, block: Dict[str, Any], intrinsic: Tuple[float, float]) -> Tuple[float, float]:
        width, height = intrinsic
        max_width = _lib.parse_length(block.get("max_width", "100%"), self.unit, base=self.frame_width, allow_percent=True, field="max_width")
        max_height = _lib.parse_length(block.get("max_height", "100%"), self.unit, base=self.frame_height, allow_percent=True, field="max_height")
        target_w = _lib.parse_length(block.get("width"), self.unit, base=self.frame_width, allow_percent=True, field="image.width")
        target_h = _lib.parse_length(block.get("height"), self.unit, base=self.frame_height, allow_percent=True, field="image.height")
        if str(block.get("fit", "contain")).lower() == "stretch" and target_w and target_h:
            return target_w, target_h
        if target_w and not target_h:
            height, width = height * (target_w / width), target_w
        elif target_h and not target_w:
            width, height = width * (target_h / height), target_h
        elif target_w and target_h:
            width, height = target_w, target_h
        if max_width and width > max_width:
            height, width = height * (max_width / width), max_width
        if max_height and height > max_height:
            width, height = width * (max_height / height), max_height
        return max(1.0, width), max(1.0, height)

    # -- markup helpers -----------------------------------------------------

    def _markup(self, block: Dict[str, Any], text: Any) -> str:
        return _lib.inline_markup(
            text, code_font=self.mono_family, allow_html=_lib.parse_bool(block.get("allow_html"), False)
        )

    def _paragraph(self, markup: str, style: Any) -> Any:
        return self.rl.Paragraph(markup if markup is not None else "", style)

    def _heading_number(self, level: int) -> str:
        self.heading_counters[level] = self.heading_counters.get(level, 0) + 1
        for deeper in [key for key in self.heading_counters if key > level]:
            del self.heading_counters[deeper]
        return ".".join(str(self.heading_counters.get(i, 1)) for i in range(1, level + 1))

    def _as_flowables(self, content: Any) -> List[Any]:
        if content is None:
            return []
        if isinstance(content, str):
            return [self._paragraph(self._markup({}, content), self.style("body"))]
        if isinstance(content, dict):
            return self.block(content)
        result: List[Any] = []
        for item in content:
            result.extend(self.block(item))
        return result

    def block(self, block: Any) -> List[Any]:
        if isinstance(block, str):
            return [self._paragraph(self._markup({}, block), self.style("body"))]
        if not isinstance(block, dict):
            raise _lib.CommandError("invalid_spec", "each content block must be an object or string")
        block_type = str(block.get("type", "paragraph"))
        handler = getattr(self, "_block_%s" % block_type, None)
        if handler is None:
            raise _lib.CommandError("invalid_spec", "unknown block type %r" % block_type)
        return [flowable for flowable in handler(block) if flowable is not None]

    # -- story --------------------------------------------------------------

    def story(self) -> List[Any]:
        blocks = list(self.spec.get("content") or [])
        toc_config = self.spec.get("toc")
        if isinstance(toc_config, dict) and not any(
            isinstance(block, dict) and block.get("type") == "toc" for block in blocks
        ):
            blocks.insert(0, dict(toc_config, type="toc"))
        flowables: List[Any] = []
        # ``fresh`` is True while the next flowable would land at the top of a
        # page, so a section break is only emitted when there is content to
        # move off the current page. This keeps the first heading (and any
        # heading right after the TOC's own page break) from adding a blank page.
        fresh = True
        cover = self.spec.get("cover")
        if cover:
            flowables.append(self.rl.NextPageTemplate("body"))
            flowables.extend(self._cover_flowables(cover))
            flowables.append(self.rl.PageBreak())
            fresh = True
        for block in blocks:
            if (
                isinstance(block, dict)
                and str(block.get("type", "paragraph")) == "heading"
                and self._heading_starts_page(block)
                and not fresh
            ):
                flowables.append(self.rl.PageBreak())
                fresh = True
            produced = self.block(block)
            flowables.extend(produced)
            for flowable in produced:
                if isinstance(flowable, self.rl.PageBreak):
                    fresh = True
                elif not isinstance(flowable, self.rl.NextPageTemplate):
                    fresh = False
        if not flowables:
            flowables.append(self.rl.Spacer(1, 1))
        return flowables

    def _encryption(self) -> Any:
        security = self._spec_dict("security")
        if not security:
            return None
        if self.rl.StandardEncryption is None:
            self.warnings.append("encryption is unavailable in this reportlab build; ignoring 'security'")
            return None
        user = security.get("user_password") or security.get("password") or ""
        owner = security.get("owner_password") or user
        if not user and not owner:
            return None
        return self.rl.StandardEncryption(
            user,
            owner,
            canPrint=int(_lib.parse_bool(security.get("can_print"), True)),
            canModify=int(_lib.parse_bool(security.get("can_modify"), True)),
            canCopy=int(_lib.parse_bool(security.get("can_copy"), True)),
            canAnnotate=int(_lib.parse_bool(security.get("can_annotate"), True)),
            strength=security.get("strength"),
        )

    def build(self, out_path: Path) -> Dict[str, Any]:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        story = self.story()
        canvas_cls, doc_cls = _doc_classes()
        meta = self._meta()
        kwargs: Dict[str, Any] = {"pagesize": self.page_size, "creator": meta["creator"]}
        if meta["title"]:
            kwargs["title"] = meta["title"]
        if meta["author"]:
            kwargs["author"] = meta["author"]
        if meta["subject"]:
            kwargs["subject"] = meta["subject"]
        if meta["keywords"]:
            kwargs["keywords"] = meta["keywords"]
        if meta["language"]:
            kwargs["lang"] = meta["language"]
        encrypt = self._encryption()
        if encrypt is not None:
            kwargs["encrypt"] = encrypt

        doc = doc_cls(str(out_path), **kwargs)
        furniture = self._furniture_config

        def on_page(canvas: Any, doc: Any) -> None:
            template = getattr(doc.pageTemplate, "id", "body")
            canvas.record(furniture.get(template) or furniture["body"])

        doc.addPageTemplates([
            self.rl.PageTemplate(
                id=template,
                frames=self._build_frames(template),
                onPage=on_page,
                pagesize=self._template_pagesize(template),
            )
            for template in self._template_order()
        ])
        try:
            if self.has_toc:
                doc.multiBuild(story, canvasmaker=canvas_cls)
            else:
                doc.build(story, canvasmaker=canvas_cls)
        except _lib.CommandError:
            raise
        except Exception as exc:
            raise _lib.CommandError("render_error", "%s: %s" % (type(exc).__name__, exc))
        pages = int(getattr(doc, "page", 0) or 0)
        width, height = self.page_size
        return {
            "out": str(out_path),
            "pages": pages,
            "bytes": out_path.stat().st_size,
            "sha256": _lib.sha256_file(out_path),
            "width_pt": round(width, 2),
            "height_pt": round(height, 2),
            "page_size": "%gx%g" % (round(width, 1), round(height, 1)),
            "orientation": self._geometry["orientation"],
            "theme": self.theme_name,
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Document template + numbered canvas (built lazily so reportlab stays optional)
# ---------------------------------------------------------------------------

_DOC_CLASSES: Optional[Tuple[Any, Any]] = None


def _doc_classes() -> Tuple[Any, Any]:
    global _DOC_CLASSES
    if _DOC_CLASSES is not None:
        return _DOC_CLASSES
    rlr = rl()

    class FurnitureCanvas(rlr.canvas.Canvas):
        """A canvas that knows the total page count when it draws furniture."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            rlr.canvas.Canvas.__init__(self, *args, **kwargs)
            self._saved_states: List[Dict[str, Any]] = []
            self._furniture_list: List[Dict[str, Any]] = []

        def record(self, config: Dict[str, Any]) -> None:
            self._furniture_list.append(config)

        def showPage(self) -> None:  # noqa: N802 - reportlab API
            self._saved_states.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._saved_states)
            for state in list(self._saved_states):
                self.__dict__.update(state)
                index = self._pageNumber - 1
                config = self._furniture_list[index] if 0 <= index < len(self._furniture_list) else None
                if config:
                    _draw_furniture(self, config, self._pageNumber, total)
                rlr.canvas.Canvas.showPage(self)
            rlr.canvas.Canvas.save(self)

    class SpecDocTemplate(rlr.BaseDocTemplate):
        """A document template that indexes headings for the TOC and outline."""

        def afterFlowable(self, flowable: Any) -> None:  # noqa: N802 - reportlab API
            level = getattr(flowable, "_toc_level", None)
            if not level:
                return
            text = getattr(flowable, "_toc_text", "")
            key = getattr(flowable, "_toc_key", "")
            try:
                self.canv.bookmarkPage(key)
            except Exception:
                pass
            try:
                self.canv.addOutlineEntry(text, key, level=max(0, min(level - 1, 4)), closed=False)
            except Exception:
                pass
            try:
                # reportlab indexes TOC levels from zero while heading levels
                # start at one; pass the zero-based level so toc1 lines up with
                # level-1 headings and the indented toc2/toc3 styles apply to
                # the headings they were written for.
                self.notify("TOCEntry", (level - 1, text, self.page, key))
            except Exception:
                pass

    _DOC_CLASSES = (FurnitureCanvas, SpecDocTemplate)
    return _DOC_CLASSES


def _draw_furniture(canvas: Any, config: Dict[str, Any], page: int, total: int) -> None:
    rlr = rl()
    mm = 72.0 / 25.4  # 1mm in points
    try:
        width, height = canvas._pagesize
    except Exception:
        return
    margins = config.get("margins") or {}
    left = float(margins.get("left", 36))
    right = width - float(margins.get("right", 36))
    top = float(margins.get("top", 36))
    bottom = float(margins.get("bottom", 36))
    header_reserve = float(config.get("header_reserve", 0))
    footer_reserve = float(config.get("footer_reserve", 0))
    meta = config.get("meta") or {}

    def tokens(text: str) -> str:
        return (
            str(text)
            .replace("{page}", str(page))
            .replace("{pages}", str(total))
            .replace("{date}", date.today().isoformat())
            .replace("{title}", str(meta.get("title", "")))
            .replace("{author}", str(meta.get("author", "")))
            .replace("{doc}", str(meta.get("title", "")))
        )

    def draw_text(text: str, y: float, spec: Dict[str, Any], default_size: float) -> None:
        if not text:
            return
        size = float(spec.get("size", default_size))
        color = _color_from(spec.get("color"), "#5B6472")
        font = spec.get("font") or "Helvetica"
        canvas.setFont(font, size)
        canvas.setFillColor(color)
        align = str(spec.get("align", "left")).lower()
        text_width = rlr.stringWidth(text, font, size)
        if align in ("center", "centre"):
            x = left + (right - left - text_width) / 2.0
        elif align == "right":
            x = right - text_width
        else:
            x = left
        canvas.drawString(x, y, text)

    background = config.get("background")
    if background:
        color = None
        if isinstance(background, str):
            color = background
        elif isinstance(background, dict):
            color = background.get("color")
        if color:
            canvas.setFillColor(_color_from(color, "#FFFFFF"))
            canvas.rect(0, 0, width, height, stroke=0, fill=1)

    header = config.get("header")
    if header:
        # Keep the running header in the top margin and leave a clear gap
        # between its rule and the first line of content. ``space_before`` on a
        # leading heading is dropped at the top of a frame, so the gap has to
        # come from moving the rule up instead.
        content_top = height - top - header_reserve
        gap = min(9 * mm, max(4 * mm, header_reserve - 1 * mm))
        divider_y = content_top + gap
        header_size = float(header.get("size", 8.5))
        header_y = min(divider_y + header_size + 2.2 * mm, height - 8 * mm)
        draw_text(tokens(header.get("text", "")), header_y, header, 8.5)
        if header.get("divider"):
            canvas.setStrokeColor(_color_from(header.get("divider_color"), "#D5DBE3"))
            canvas.setLineWidth(float(header.get("divider_width", 0.5)))
            canvas.line(left, divider_y, right, divider_y)

    footer = config.get("footer")
    footer_has_number = bool(footer and ("{page}" in str(footer.get("text", "")) or "{pages}" in str(footer.get("text", ""))))
    # Best practice: the footer sits in the bottom margin, about 12mm from the
    # trim edge, so the page number reads as a footer rather than body copy.
    footer_y = min(12 * mm, max(8 * mm, bottom - 4 * mm))
    if footer:
        draw_text(tokens(footer.get("text", "")), footer_y, footer, 8.5)
    if config.get("page_numbers") and not footer_has_number:
        canvas.setFont("Helvetica", 8.5)
        canvas.setFillColor(_color_from(None, "#5B6472"))
        label = "%d / %d" % (page, total)
        canvas.drawCentredString((left + right) / 2.0, footer_y, label)

    watermark = config.get("watermark")
    if watermark and watermark.get("text"):
        size = float(watermark.get("size", 72))
        color = _color_from(watermark.get("color"), "#E2E5EA")
        opacity = float(watermark.get("opacity", 0.18))
        angle = float(watermark.get("angle", 45))
        font = watermark.get("font") or "Helvetica"
        canvas.saveState()
        canvas.setFillColor(color)
        try:
            canvas.setFillAlpha(opacity)
        except Exception:
            pass
        canvas.translate(width / 2.0, height / 2.0)
        canvas.rotate(angle)
        text = str(watermark["text"])
        text_width = rlr.stringWidth(text, font, size)
        canvas.setFont(font, size)
        canvas.drawString(-text_width / 2.0, -size / 3.0, text)
        canvas.restoreState()


def _color_from(value: Any, default: str) -> Any:
    from _lib import parse_color

    r, g, b, a = parse_color(value if value is not None else default)
    return rl().colors.Color(r, g, b, alpha=a)


def build_pdf(
    spec: Dict[str, Any],
    out_path: Path,
    *,
    home: Path,
    base_dir: Optional[Path] = None,
    settings: Optional[Dict[str, str]] = None,
    allow_remote: bool = False,
) -> Dict[str, Any]:
    """Render ``spec`` to ``out_path`` and return render statistics."""
    builder = Builder(spec, home=home, base_dir=base_dir, settings=settings, allow_remote=allow_remote)
    return builder.build(Path(out_path))
