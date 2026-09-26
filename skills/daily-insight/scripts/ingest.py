#!/usr/bin/env python3
"""Ingest source material into chunks, embeddings, and the vector store.

Accepts pasted text (``--text`` or stdin) or files (``.txt``, ``.md``, ``.rst``,
``.csv``, ``.json``, ``.html``, ``.docx``, ``.pdf``). Chunks are embedded with
the configured backend and written to SQLite and Chroma together. Re-ingesting
the same content is a no-op unless ``--replace`` is passed.
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _lib  # noqa: E402

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".log", ".text"}
HTML_SUFFIXES = {".html", ".htm", ".xhtml"}


def _require(module: str, package: str) -> Any:
    try:
        return __import__(module)
    except Exception:
        raise _lib.CommandError(
            "dependency_missing",
            "reading this file needs %s: pip install -r requirements.txt" % package,
        )


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    return re.sub(r"[ \t]+", " ", text)


def extract_text(path: Path) -> str:
    if not path.exists():
        raise _lib.CommandError("not_found", "no such file: %s" % path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        docx = _require("docx", "python-docx")
        document = docx.Document(str(path))
        parts = [para.text for para in document.paragraphs if para.text and para.text.strip()]
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n\n".join(parts)
    if suffix == ".pdf":
        pypdf = _require("pypdf", "pypdf")
        reader = pypdf.PdfReader(str(path))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pages.append("")
        return "\n\n".join(pages)
    raw = path.read_text(encoding="utf-8", errors="replace")
    if suffix in HTML_SUFFIXES:
        return _strip_html(raw)
    return raw


def _read_stdin() -> str:
    try:
        return sys.stdin.read()
    except Exception:
        return ""


def _ensure_material(
    conn: sqlite3.Connection,
    name: str,
    source_path: Optional[str],
) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM materials WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO materials (name, source_path) VALUES (?, ?)", (name, source_path)
        )
        row = conn.execute(
            "SELECT * FROM materials WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
    elif source_path and not row["source_path"]:
        conn.execute("UPDATE materials SET source_path = ? WHERE id = ?", (source_path, row["id"]))
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (row["id"],)).fetchone()
    return row


def _existing_hashes(conn: sqlite3.Connection, material_id: int) -> set:
    rows = conn.execute(
        "SELECT text_hash FROM chunks WHERE material_id = ?", (material_id,)
    ).fetchall()
    return {row["text_hash"] for row in rows}


def _max_ordinal(conn: sqlite3.Connection, material_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(ordinal), -1) AS n FROM chunks WHERE material_id = ?",
        (material_id,),
    ).fetchone()
    return int(row["n"])


def cmd_ingest(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    if args.chunk_size is not None and args.chunk_size < 20:
        raise _lib.CommandError("invalid_input", "--chunk-size must be 20 or greater")
    size = args.chunk_size if args.chunk_size is not None else _lib.setting_int(conn, "chunk_size", _lib.DEFAULT_CHUNK_SIZE)
    overlap = args.chunk_overlap if args.chunk_overlap is not None else _lib.setting_int(conn, "chunk_overlap", _lib.DEFAULT_CHUNK_OVERLAP)
    dry_run = bool(args.dry_run)

    inputs: List[Tuple[str, str, Optional[str]]] = []
    if args.text is not None:
        inputs.append((args.material or args.title or "pasted", args.text, None))
    for file_name in args.files or []:
        path = Path(os.path.expanduser(file_name))
        if not path.exists():
            raise _lib.CommandError("not_found", "no such file: %s" % file_name)
        name = args.material or args.title or path.stem
        inputs.append((name, extract_text(path), str(path)))
    if not inputs:
        if sys.stdin.isatty():
            raise _lib.CommandError(
                "usage", "ingest needs a file argument, --text, or piped stdin"
            )
        piped = _read_stdin()
        if not piped.strip():
            raise _lib.CommandError("invalid_input", "no input text was provided")
        if not (args.material or args.title):
            raise _lib.CommandError("usage", "stdin ingest needs --material or --title")
        inputs.append((args.material or args.title, piped, None))

    if not _lib.deps_status().get("chromadb"):
        raise _lib.CommandError(
            "dependency_missing",
            "ingest needs the vector store: pip install -r requirements.txt",
        )

    collection = None if dry_run else _lib.open_collection(home)
    material_rows: Dict[str, sqlite3.Row] = {}
    source_reports: List[Dict[str, Any]] = []
    total_added = 0
    total_skipped = 0
    embedded = 0
    replaced_ids: List[int] = []

    for name, text, source_path in inputs:
        if dry_run:
            existing = conn.execute(
                "SELECT * FROM materials WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
            material = existing if existing is not None else {
                "id": -1, "name": name, "chunk_count": 0, "source_path": source_path
            }
        else:
            material = material_rows.get(name)
            if material is None:
                material = _ensure_material(conn, name, source_path)
                material_rows[name] = material

        material_id = int(material["id"])

        if args.replace and not dry_run and material_id > 0:
            conn.execute("DELETE FROM chunks WHERE material_id = ?", (material_id,))
            if collection is not None:
                _lib.chroma_delete_material(collection, material_id)
            replaced_ids.append(material_id)

        existing_hashes = set()
        if material_id > 0 and not (args.replace and not dry_run):
            existing_hashes = _existing_hashes(conn, material_id)
        seen = set(existing_hashes)

        chunks = _lib.chunk_text(text, size, overlap)
        picked: List[Tuple[str, str]] = []
        skipped = 0
        for piece in chunks:
            digest = _lib.sha256_text(piece)
            if digest in seen:
                skipped += 1
                continue
            seen.add(digest)
            picked.append((piece, digest))

        added = len(picked)
        if not dry_run and added:
            start_ordinal = 0 if args.replace else (_max_ordinal(conn, material_id) + 1)
            ordinals = list(range(start_ordinal, start_ordinal + added))
            vectors = _lib.embed_texts(conn, [piece for piece, _ in picked])
            embedded += len(vectors)
            for offset, ((piece, digest), ordinal) in enumerate(zip(picked, ordinals)):
                conn.execute(
                    "INSERT INTO chunks (material_id, ordinal, text, token_est, text_hash) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (material_id, ordinal, piece, _lib.estimate_tokens(piece), digest),
                )
            if collection is not None:
                _lib.chroma_add(
                    collection,
                    material_id,
                    ordinals,
                    [piece for piece, _ in picked],
                    vectors,
                    [digest for _, digest in picked],
                )
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM chunks WHERE material_id = ?", (material_id,)
            ).fetchone()["n"]
            conn.execute(
                "UPDATE materials SET chunk_count = ?, source_path = COALESCE(?, source_path), "
                "source_hash = ? WHERE id = ?",
                (
                    count,
                    source_path,
                    _lib.sha256_text(text),
                    material_id,
                ),
            )

        total_added += added
        total_skipped += skipped
        source_report = {
            "material": name,
            "source_path": source_path,
            "chars": len(text),
            "chunks_found": len(chunks),
            "chunks_added": added,
            "chunks_skipped": skipped,
        }
        if dry_run:
            source_report["material_would_be_created"] = material_id <= 0
        source_reports.append(source_report)

    result: Dict[str, Any] = {
        "dry_run": dry_run,
        "chunk_size": size,
        "chunk_overlap": overlap,
        "replace": bool(args.replace),
        "sources": source_reports,
        "chunks_added": total_added,
        "chunks_skipped": total_skipped,
        "embedded": embedded,
    }
    if dry_run:
        result["note"] = "dry run: nothing was written and no embeddings were requested"
    else:
        touched = sorted(material_rows.values(), key=lambda row: str(row["name"]))
        result["materials"] = [
            _lib.material_dict(conn, _lib.resolve_material(conn, int(row["id"])))
            for row in touched
            if int(row["id"]) > 0
        ]
    return result


def build_parser() -> argparse.ArgumentParser:
    common = _lib.common_parser()
    parser = argparse.ArgumentParser(
        prog="ingest.py", description="Ingest text or files into the daily-insight vector store."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest = _lib.add_subparser(subparsers, "ingest", "chunk, embed, and store content", [common])
    ingest.add_argument("files", nargs="*", help="files to ingest (.md, .txt, .html, .docx, .pdf, ...)")
    ingest.add_argument("--text", help="raw text to ingest instead of a file")
    ingest.add_argument("--material", help="material name (created if new)")
    ingest.add_argument("--title", help="material name when --material is omitted")
    ingest.add_argument("--chunk-size", type=int, help="override the configured chunk size")
    ingest.add_argument("--chunk-overlap", type=int, help="override the configured overlap")
    ingest.add_argument("--replace", action="store_true", help="delete existing chunks first")
    ingest.add_argument("--dry-run", action="store_true", help="report without writing anything")
    ingest.set_defaults(func=cmd_ingest)
    return parser


def main() -> None:
    _lib.run_script("ingest", build_parser())


if __name__ == "__main__":
    main()
