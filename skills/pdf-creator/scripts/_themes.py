#!/usr/bin/env python3
"""Built-in palette, themes, and paragraph-style defaults for pdf-creator.

Data-only module: it imports no rendering library so it can be imported by the
validator and the tests without reportlab present. Style props use the
skill's own keys (``font_family``, ``font_size``, ``space_after``, ...); the
engine maps them to reportlab ``ParagraphStyle`` attributes.

The house style is modern and sans-serif: near-black type, generous spacing,
one restrained accent, light surfaces, and hairline rules rather than heavy
boxes. Serif families remain available; set one explicitly in a spec's
``font`` or a ``styles`` override if you want it.
"""
from __future__ import annotations

from typing import Any, Dict

BASE_PALETTE: Dict[str, str] = {
    "text": "#111827",
    "muted": "#6B7280",
    "accent": "#7C3AED",
    "accent_soft": "#F5F3FF",
    "border": "#E5E7EB",
    "surface": "#F9FAFB",
    "header_bg": "#F3F4F6",
    "header_text": "#111827",
    "zebra": "#FAFAFA",
    "link": "#6D28D9",
    "code_bg": "#F6F7F9",
    "code_text": "#1F2937",
    "success": "#059669",
    "success_soft": "#ECFDF5",
    "warning": "#D97706",
    "warning_soft": "#FFFBEB",
    "danger": "#DC2626",
    "danger_soft": "#FEF2F2",
    "info": "#4F46E5",
    "info_soft": "#EEF2FF",
}

# Each theme overrides palette entries and a few style props. Styles are merged
# over the base styles so a theme only states what it changes. Every theme is
# sans-serif by default; pick a serif family explicitly for a more formal look.
THEMES: Dict[str, Dict[str, Any]] = {
    "default": {
        "label": "Modern sans-serif with a restrained violet accent.",
        "palette": {},
        "font_family": "Helvetica",
        "styles": {},
    },
    "report": {
        "label": "Airy modern report with a table of contents and uncluttered sections.",
        "palette": {"accent": "#6D28D9", "link": "#6D28D9"},
        "font_family": "Helvetica",
        "styles": {
            "body": {"font_size": 10.6, "leading": 16, "color": "#1F2937"},
            "h1": {"space_before": 24, "space_after": 8},
            "lead": {"font_size": 12.5, "leading": 18.5},
        },
        "header": {"align": "right", "size": 8.3, "color": "#9CA3AF"},
        "footer": {"align": "center", "size": 8.3, "color": "#9CA3AF", "text": "{page} / {pages}"},
    },
    "invoice": {
        "label": "Clean sans-serif business layout tuned for tables and totals.",
        "palette": {"accent": "#0D9488", "link": "#0D9488", "zebra": "#F0FDFA"},
        "font_family": "Helvetica",
        "styles": {
            "body": {"font_size": 10.2, "leading": 15},
            "table_cell": {"font_size": 9.4, "leading": 12.5},
        },
    },
    "letter": {
        "label": "Spacious sans-serif stationery with wide margins.",
        "palette": {"accent": "#374151", "link": "#374151"},
        "font_family": "Helvetica",
        "page": {"margins": "27mm"},
        "styles": {
            "body": {"font_size": 11.2, "line_height": 1.55},
            "title": {"font_size": 24},
        },
        "footer": {"align": "right", "size": 8, "color": "#9CA3AF", "text": "{page}"},
    },
    "resume": {
        "label": "Dense sans-serif resume with tight section spacing.",
        "palette": {"accent": "#111827", "link": "#111827", "muted": "#4B5563"},
        "font_family": "Helvetica",
        "styles": {
            "body": {"font_size": 10, "leading": 13.5},
            "h1": {"font_size": 20, "space_before": 12, "space_after": 5},
            "h2": {"font_size": 11.8, "space_before": 11, "space_after": 3},
        },
    },
    "book": {
        "label": "Reading-first sans-serif with roomy leading and an indented first line.",
        "palette": {"accent": "#1F2937", "link": "#1F2937", "muted": "#6B7280"},
        "font_family": "Helvetica",
        "styles": {
            "body": {"font_size": 11.2, "line_height": 1.65, "first_line_indent": "5mm"},
            "h1": {"font_size": 19},
        },
    },
    "minimal": {
        "label": "Near-monochrome and rule-free: content only.",
        "palette": {
            "accent": "#111827",
            "link": "#111827",
            "muted": "#6B7280",
            "border": "#E5E7EB",
            "surface": "#FAFAFA",
            "header_bg": "#FAFAFA",
        },
        "font_family": "Helvetica",
        "styles": {},
        "header": None,
        "footer": None,
    },
    "elegant": {
        "label": "Warm modern sans-serif with stone neutrals and an amber accent.",
        "palette": {
            "accent": "#B45309",
            "link": "#B45309",
            "accent_soft": "#FFFBEB",
            "muted": "#78716C",
            "border": "#E7E5E4",
            "surface": "#FAFAF9",
            "header_bg": "#F5F5F4",
            "zebra": "#FAFAF9",
        },
        "font_family": "Helvetica",
        "styles": {
            "title": {"font_size": 30},
            "h1": {"space_before": 22},
        },
    },
}

# Named paragraph styles, before theme and inline overrides. A value that
# starts with ``@`` is a palette key ("@accent") or a family selector
# ("@family_bold", "@mono"). Bare numbers use the document unit for lengths and
# points for font sizes and leading unless a unit suffix is given.
#
# Headings are near-black by default; the accent is reserved for the cover
# eyebrow, links, and small markers so documents read modern rather than
# corporate.
BASE_STYLE_PROPS: Dict[str, Dict[str, Any]] = {
    "title": {
        "font_size": 30, "leading": 34, "color": "@text", "align": "left",
        "space_after": 6, "font_family": "@family_bold",
    },
    "subtitle": {"font_size": 14, "leading": 19, "color": "@muted", "space_after": 14},
    "lead": {"font_size": 12.5, "leading": 18, "color": "@muted", "space_after": 10},
    "body": {"space_after": 8},
    "h1": {
        "font_size": 21, "leading": 25, "color": "@text", "space_before": 22,
        "space_after": 7, "font_family": "@family_bold", "keep_with_next": True,
    },
    "h2": {
        "font_size": 15.5, "leading": 19, "color": "@text", "space_before": 16,
        "space_after": 5, "font_family": "@family_bold", "keep_with_next": True,
    },
    "h3": {
        "font_size": 12.8, "leading": 16, "color": "@text", "space_before": 13,
        "space_after": 4, "font_family": "@family_bold", "keep_with_next": True,
    },
    "h4": {
        "font_size": 11.2, "leading": 14, "color": "@text", "space_before": 11,
        "space_after": 3, "font_family": "@family_bold", "keep_with_next": True,
    },
    "h5": {
        "font_size": 10.6, "leading": 13, "color": "@muted", "space_before": 10,
        "space_after": 3, "font_family": "@family_bold", "keep_with_next": True,
    },
    "h6": {
        "font_size": 10.6, "leading": 13, "color": "@muted", "space_before": 10,
        "space_after": 3, "font_family": "@family_bold_italic", "keep_with_next": True,
    },
    "caption": {
        "font_size": 8.4, "leading": 11, "color": "@muted", "align": "center",
        "space_before": 4, "space_after": 10,
    },
    "small": {"font_size": 8.5, "leading": 11, "color": "@muted"},
    "code": {"font_family": "@mono", "font_size": 8.8, "leading": 12, "color": "@code_text"},
    "quote": {"color": "@muted", "left_indent": 14, "space_after": 10},
    "table_header": {
        "font_family": "@family_bold", "font_size": 9.3, "leading": 12, "color": "@text",
    },
    "table_cell": {"font_size": 9.3, "leading": 12.5, "color": "@text"},
    "table_caption": {
        "font_size": 8.3, "leading": 10.5, "color": "@muted", "space_before": 4, "space_after": 10,
    },
    "toc_title": {
        "font_size": 17, "leading": 21, "color": "@text", "space_after": 10,
        "font_family": "@family_bold",
    },
    "toc1": {"font_size": 10.5, "leading": 15, "color": "@text", "font_family": "@family_bold"},
    "toc2": {"font_size": 10, "leading": 14, "color": "@muted", "left_indent": 14},
    "toc3": {"font_size": 9.5, "leading": 13, "color": "@muted", "left_indent": 28},
    "definition_term": {"font_family": "@family_bold", "space_after": 1, "keep_with_next": True},
    "definition_body": {"color": "@muted", "left_indent": 12, "space_after": 7},
    "key": {"font_family": "@family_bold", "align": "right", "color": "@muted"},
    "value": {"align": "left"},
    "callout_title": {"font_family": "@family_bold", "space_after": 4},
    "callout_body": {"space_after": 0},
    "header": {"font_size": 8.3, "leading": 10, "color": "@muted"},
    "footer": {"font_size": 8.3, "leading": 10, "color": "@muted"},
    "watermark": {"font_size": 72, "leading": 80, "color": "#E5E7EB"},
}

ALIGNMENTS = {
    "left": "TA_LEFT",
    "start": "TA_LEFT",
    "center": "TA_CENTER",
    "centre": "TA_CENTER",
    "right": "TA_RIGHT",
    "end": "TA_RIGHT",
    "justify": "TA_JUSTIFY",
    "justified": "TA_JUSTIFY",
}

# Style-prop key -> ParagraphStyle attribute, when they differ. ``None`` means
# the engine resolves it specially (font name, leading derivation).
STYLE_ATTRS: Dict[str, Any] = {
    "font_family": None,
    "font_size": "fontSize",
    "leading": "leading",
    "line_height": None,
    "color": "textColor",
    "align": "alignment",
    "space_before": "spaceBefore",
    "space_after": "spaceAfter",
    "left_indent": "leftIndent",
    "right_indent": "rightIndent",
    "first_line_indent": "firstLineIndent",
    "bullet_indent": "bulletIndent",
    "bullet_font": "bulletFontName",
    "bullet_size": "bulletFontSize",
    "back_color": "backColor",
    "border_width": "borderWidth",
    "border_color": "borderColor",
    "border_padding": "borderPadding",
    "border_radius": "borderRadius",
    "keep_with_next": "keepWithNext",
    "word_wrap": "wordWrap",
    "allow_widows": "allowWidows",
    "allow_orphans": "allowOrphans",
    "underline": "underline",
}
