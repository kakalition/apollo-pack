#!/usr/bin/env python3
"""Lazy reportlab loader shared by the pdf-creator rendering modules.

The skill stays importable without reportlab: :func:`rl` performs the import on
first use and raises ``dependency_missing`` when the engine is absent. All
reportlab names the renderer needs are cached in one namespace so the rest of
the code reads naturally (``rl().Table``, ``rl().Paragraph``, ...).
"""
from __future__ import annotations

import types
from typing import Optional

from _lib import CommandError

_HINT = (
    "rendering needs the reportlab engine: pip install -r requirements.txt "
    "(or `uv pip install reportlab`)"
)

_NAMESPACE: Optional[types.SimpleNamespace] = None


def rl() -> types.SimpleNamespace:
    global _NAMESPACE
    if _NAMESPACE is not None:
        return _NAMESPACE
    try:
        from reportlab.lib import colors, pagesizes
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm, inch, mm, pica
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.pdfmetrics import registerFontFamily, stringWidth
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
        from reportlab.platypus import (
            BaseDocTemplate,
            CondPageBreak,
            Flowable,
            Frame,
            FrameBreak,
            HRFlowable,
            Image,
            KeepInFrame,
            KeepTogether,
            ListFlowable,
            ListItem,
            NextPageTemplate,
            PageBreak,
            PageTemplate,
            Paragraph,
            Preformatted,
            Spacer,
            Table,
            TableStyle,
            XPreformatted,
        )
        from reportlab.platypus.tableofcontents import TableOfContents
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise CommandError("dependency_missing", _HINT) from exc

    namespace = types.SimpleNamespace(
        colors=colors,
        pagesizes=pagesizes,
        TA_CENTER=TA_CENTER,
        TA_JUSTIFY=TA_JUSTIFY,
        TA_LEFT=TA_LEFT,
        TA_RIGHT=TA_RIGHT,
        ParagraphStyle=ParagraphStyle,
        cm=cm,
        inch=inch,
        mm=mm,
        pica=pica,
        ImageReader=ImageReader,
        pdfmetrics=pdfmetrics,
        registerFontFamily=registerFontFamily,
        stringWidth=stringWidth,
        TTFont=TTFont,
        canvas=canvas,
        BaseDocTemplate=BaseDocTemplate,
        CondPageBreak=CondPageBreak,
        Flowable=Flowable,
        Frame=Frame,
        FrameBreak=FrameBreak,
        HRFlowable=HRFlowable,
        Image=Image,
        KeepInFrame=KeepInFrame,
        KeepTogether=KeepTogether,
        ListFlowable=ListFlowable,
        ListItem=ListItem,
        NextPageTemplate=NextPageTemplate,
        PageBreak=PageBreak,
        PageTemplate=PageTemplate,
        Paragraph=Paragraph,
        Preformatted=Preformatted,
        Spacer=Spacer,
        Table=Table,
        TableStyle=TableStyle,
        XPreformatted=XPreformatted,
        TableOfContents=TableOfContents,
    )
    try:
        from reportlab.lib.pdfencrypt import StandardEncryption

        namespace.StandardEncryption = StandardEncryption
    except ImportError:  # pragma: no cover
        namespace.StandardEncryption = None
    try:
        from reportlab.graphics.barcode import createBarcodeDrawing

        namespace.createBarcodeDrawing = createBarcodeDrawing
    except ImportError:  # pragma: no cover
        namespace.createBarcodeDrawing = None
    try:
        from reportlab.graphics.barcode import qr

        namespace.qr = qr
    except ImportError:  # pragma: no cover
        namespace.qr = None

    _NAMESPACE = namespace
    return namespace
