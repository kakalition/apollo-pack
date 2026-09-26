#!/usr/bin/env python3
"""A small, dependency-free Markdown-to-blocks converter for pdf-creator.

It supports the subset an agent most often writes: ATX headings, paragraphs,
unordered and ordered lists (one nesting level), fenced code blocks,
blockquotes, horizontal rules, tables with a header separator, and pipe rows.
Inline emphasis is left intact for the renderer's inline markup pass.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_RULE_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _split_row(line: str) -> List[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _is_block_start(line: str) -> bool:
    if not line.strip():
        return True
    return bool(
        _HEADING_RE.match(line)
        or _RULE_RE.match(line)
        or _LIST_RE.match(line)
        or _QUOTE_RE.match(line)
        or line.strip().startswith("```")
        or line.strip().startswith("|")
    )


def from_markdown(text: str) -> List[Dict[str, Any]]:
    """Convert Markdown ``text`` to a list of pdf-creator content blocks."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: List[Dict[str, Any]] = []
    index = 0
    while index < len(lines):
        line = lines[index]

        if line.strip().startswith("```"):
            language = line.strip()[3:].strip()
            index += 1
            buffer: List[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                buffer.append(lines[index])
                index += 1
            index += 1
            block: Dict[str, Any] = {"type": "code", "text": "\n".join(buffer)}
            if language:
                block["language"] = language
            blocks.append(block)
            continue

        match = _HEADING_RE.match(line)
        if match:
            blocks.append({"type": "heading", "level": len(match.group(1)), "text": match.group(2).strip()})
            index += 1
            continue

        if _RULE_RE.match(line):
            blocks.append({"type": "divider"})
            index += 1
            continue

        if _QUOTE_RE.match(line):
            buffer = []
            while index < len(lines) and _QUOTE_RE.match(lines[index]):
                buffer.append(_QUOTE_RE.match(lines[index]).group(1))
                index += 1
            blocks.append({"type": "blockquote", "text": "\n".join(buffer)})
            continue

        if line.strip().startswith("|") and index + 1 < len(lines) and _TABLE_SEP_RE.match(lines[index + 1]):
            header = _split_row(line)
            index += 2
            rows: List[List[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(_split_row(lines[index]))
                index += 1
            blocks.append({"type": "table", "header": header, "rows": rows})
            continue

        list_match = _LIST_RE.match(line)
        if list_match:
            ordered = list_match.group(2)[0].isdigit()
            base_indent = len(list_match.group(1))
            items: List[Any] = []
            while index < len(lines):
                current = _LIST_RE.match(lines[index])
                if not current or len(current.group(1)) < base_indent:
                    break
                if len(current.group(1)) > base_indent:
                    nested: List[str] = []
                    while index < len(lines) and _LIST_RE.match(lines[index]) and len(_LIST_RE.match(lines[index]).group(1)) > base_indent:
                        nested.append(_LIST_RE.match(lines[index]).group(3).strip())
                        index += 1
                    if items:
                        last = items[-1]
                        text_value = last if isinstance(last, str) else last.get("text", "")
                        items[-1] = {"text": text_value, "items": nested}
                    continue
                items.append(current.group(3).strip())
                index += 1
            blocks.append({"type": "list", "ordered": ordered, "items": items})
            continue

        if not line.strip():
            index += 1
            continue

        buffer = [line.strip()]
        index += 1
        while index < len(lines) and lines[index].strip() and not _is_block_start(lines[index]):
            buffer.append(lines[index].strip())
            index += 1
        blocks.append({"type": "paragraph", "text": " ".join(buffer)})

    return blocks
