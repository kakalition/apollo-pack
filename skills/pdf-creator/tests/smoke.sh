#!/usr/bin/env bash
# End-to-end smoke test for the pdf-creator skill.
#
# Runs every script and verb against throwaway data roots and checks the JSON
# envelope, the state, the library, the asset store, rendering (pages, output
# files), Markdown conversion, the scheduler artifact matrix (including
# executing the emitted report command twice), error handling, and portability.
# Fixtures (a PNG and a Markdown file) are generated at run time, so nothing
# binary is committed. Rendering sections are skipped when reportlab is absent;
# the state, library, and asset verbs are still exercised.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILL="$ROOT"
SCRIPTS="$SKILL/scripts"
PY="${PY:-python3}"
export PYTHONWARNINGS="ignore"

PASS=0
FAIL=0
TMPDIR_SMOKE="$(mktemp -d "${TMPDIR:-/tmp}/pcf-smoke.XXXXXX")"
cleanup() { rm -rf "$TMPDIR_SMOKE"; }
trap cleanup EXIT

pass() { PASS=$((PASS + 1)); }
fail() { FAIL=$((FAIL + 1)); printf 'FAIL: %s\n' "$*" >&2; }
section() { printf '\n== %s ==\n' "$*"; }

check() { # check DESC ACTUAL EXPECTED
  if [ "$2" = "$3" ]; then pass; else fail "$1: expected [$3] got [$2]"; fi
}

jqv() { "$PY" -c 'import json,sys
d=json.load(sys.stdin)
print(eval(sys.argv[1]))' "$1"; }

run() { "$PY" "$@"; }

expect_fail() { # expect_fail DESC CODE CMD...
  local desc="$1" code="$2"; shift 2
  local out rc
  out="$("$@" 2>/dev/null)"; rc=$?
  if [ "$rc" -eq 1 ]; then pass; else fail "$desc: expected exit 1, got $rc"; fi
  check "$desc code" "$(printf '%s' "$out" | jqv "d['error']['code']")" "$code"
}

have_reportlab() { "$PY" -c 'import reportlab' >/dev/null 2>&1; }
have_pypdf() { "$PY" -c 'import pypdf' >/dev/null 2>&1; }

HAVE_RL=0
have_reportlab && HAVE_RL=1

unset PDF_CREATOR_HOME PDF_CREATOR_PAGE_SIZE PDF_CREATOR_THEME PDF_CREATOR_OUTPUT_DIR 2>/dev/null || true

export PDF_CREATOR_HOME="$TMPDIR_SMOKE/home"

# Fixtures ------------------------------------------------------------------
"$PY" - "$TMPDIR_SMOKE" <<'PY'
import struct, sys, zlib
from pathlib import Path
base = Path(sys.argv[1])
def png(w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
(base / "logo.png").write_bytes(png(48, 20, (30, 90, 200)))
(base / "guide.md").write_text(
    "# Field Guide\n\nA short **guide** with `code` and a [link](https://example.com).\n\n"
    "## Items\n- Alpha\n- Beta\n  - Nested\n1. First\n2. Second\n\n"
    "> A quote worth keeping.\n\n"
    "| Name | Value |\n| --- | --- |\n| One | 1 |\n| Two | 2 |\n\n"
    "```python\nprint(\"hello\")\n```\n",
    encoding="utf-8",
)
(base / "var_spec.json").write_text(
    '{"spec_version":1,"meta":{"title":"Invoice {{number}}"},"theme":"invoice",'
    '"footer":{"text":"{page} / {pages}","align":"center"},'
    '"content":[{"type":"heading","level":1,"text":"Invoice {{number}}"},'
    '{"type":"paragraph","text":"For {{client}}."},'
    '{"type":"table","header":["Item","Amount"],"zebra":true,'
    '"rows":[["Work","$100"],[{"text":"Total","bold":true},{"text":"$100","bold":true}]]}]}\n',
    encoding="utf-8",
)
(base / "secure_spec.json").write_text(
    '{"spec_version":1,"meta":{"title":"Secret"},'
    '"security":{"user_password":"open-sesame","can_copy":false},'
    '"content":[{"type":"heading","level":1,"text":"Confidential"}]}\n',
    encoding="utf-8",
)
(base / "tall.png").write_bytes(png(16, 320, (200, 30, 30)))
(base / "layout_spec.json").write_text(
    '{"spec_version":1,"meta":{"title":"Layout"},'
    '"header":{"text":"Layout","align":"left","divider":true},'
    '"footer":{"text":"Page {page} of {pages}","align":"right"},'
    '"toc":{"title":"Contents","depth":3},'
    '"content":[{"type":"heading","level":1,"text":"Start"},'
    '{"type":"image","src":"tall.png","width":"50%"},'
    '{"type":"page_template","name":"landscape","break":"before"},'
    '{"type":"heading","level":1,"text":"Wide"},'
    '{"type":"paragraph","text":"Wide text. "}]}\n',
    encoding="utf-8",
)
(base / "sections_spec.json").write_text(
    '{"spec_version":1,"meta":{"title":"Sections"},'
    '"toc":{"title":"Contents","depth":2},"page_break_headings":1,'
    '"content":[{"type":"heading","level":1,"text":"Alpha"},'
    '{"type":"paragraph","text":"Alpha body."},'
    '{"type":"heading","level":2,"text":"Alpha sub"},'
    '{"type":"paragraph","text":"Alpha sub body."},'
    '{"type":"heading","level":1,"text":"Beta"},'
    '{"type":"paragraph","text":"Beta body."},'
    '{"type":"heading","level":1,"text":"Gamma"},'
    '{"type":"paragraph","text":"Gamma body."}]}\n',
    encoding="utf-8",
)
PY

# ===========================================================================
section "init / settings"
OUT="$(run "$SCRIPTS/init.py" init)"
check "init ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
check "init schema" "$(printf '%s' "$OUT" | jqv "d['data']['schema_version']")" "1"
check "init first run" "$(printf '%s' "$OUT" | jqv "d['data']['already_initialized']")" "False"
check "init dependencies has reportlab key" "$(printf '%s' "$OUT" | jqv "'reportlab' in d['data']['dependencies']")" "True"
OUT="$(run "$SCRIPTS/init.py" init)"
check "init idempotent" "$(printf '%s' "$OUT" | jqv "d['data']['already_initialized']")" "True"

OUT="$(run "$SCRIPTS/settings.py" show)"
check "settings default page size" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['page_size']")" "A4"
check "settings default theme" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['theme']")" "default"

OUT="$(run "$SCRIPTS/settings.py" set --theme report --page-size Letter --author Ada --margin 22mm)"
check "settings set theme" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['theme']")" "report"
check "settings set margin" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['margin_top']")" "22mm"
OUT="$(run "$SCRIPTS/settings.py" get --key author)"
check "settings get" "$(printf '%s' "$OUT" | jqv "d['data']['value']")" "Ada"
run "$SCRIPTS/settings.py" set --page-size A4 --theme default >/dev/null
expect_fail "settings set with no flags" "invalid_input" "$PY" "$SCRIPTS/settings.py" set

# ===========================================================================
section "documents"
OUT="$(run "$SCRIPTS/documents.py" save --name invoice --spec "$TMPDIR_SMOKE/var_spec.json" --tags billing,demo)"
check "save created" "$(printf '%s' "$OUT" | jqv "d['data']['created']")" "True"
expect_fail "save duplicate" "conflict" "$PY" "$SCRIPTS/documents.py" save --name invoice --spec "$TMPDIR_SMOKE/var_spec.json"
OUT="$(run "$SCRIPTS/documents.py" save --name invoice --spec "$TMPDIR_SMOKE/var_spec.json" --force)"
check "save overwrite" "$(printf '%s' "$OUT" | jqv "d['data']['overwritten']")" "True"
OUT="$(run "$SCRIPTS/documents.py" list)"
check "list count" "$(printf '%s' "$OUT" | jqv "d['data']['count']")" "1"
OUT="$(run "$SCRIPTS/documents.py" show invoice)"
check "show blocks" "$(printf '%s' "$OUT" | jqv "d['data']['blocks']")" "3"
OUT="$(run "$SCRIPTS/documents.py" rename invoice invoice-2)"
check "rename" "$(printf '%s' "$OUT" | jqv "d['data']['name']")" "invoice-2"
OUT="$(run "$SCRIPTS/documents.py" duplicate invoice-2 invoice-copy)"
check "duplicate" "$(printf '%s' "$OUT" | jqv "d['data']['name']")" "invoice-copy"
OUT="$(run "$SCRIPTS/documents.py" export invoice-2 --out "$TMPDIR_SMOKE/exported.json")"
check "export file" "$(printf '%s' "$OUT" | jqv "d['data']['bytes'] > 0")" "True"
expect_fail "delete without yes" "invalid_input" "$PY" "$SCRIPTS/documents.py" delete invoice-copy
run "$SCRIPTS/documents.py" delete invoice-copy --yes >/dev/null
OUT="$(run "$SCRIPTS/documents.py" list)"
check "list after delete" "$(printf '%s' "$OUT" | jqv "d['data']['count']")" "1"
expect_fail "show unknown doc" "not_found" "$PY" "$SCRIPTS/documents.py" show ghost

# ===========================================================================
section "assets"
OUT="$(run "$SCRIPTS/assets.py" add-image "$TMPDIR_SMOKE/logo.png" --name logo.png)"
check "add image" "$(printf '%s' "$OUT" | jqv "d['data']['name']")" "logo.png"
expect_fail "add image duplicate" "conflict" "$PY" "$SCRIPTS/assets.py" add-image "$TMPDIR_SMOKE/logo.png" --name logo.png
OUT="$(run "$SCRIPTS/assets.py" list --type image)"
check "asset list" "$(printf '%s' "$OUT" | jqv "len(d['data']['images'])")" "1"
OUT="$(run "$SCRIPTS/assets.py" paths)"
check "paths has fonts" "$(printf '%s' "$OUT" | jqv "'fonts' in d['data']")" "True"
run "$SCRIPTS/assets.py" remove logo.png >/dev/null
OUT="$(run "$SCRIPTS/assets.py" list --type image)"
check "asset removed" "$(printf '%s' "$OUT" | jqv "len(d['data']['images'])")" "0"
expect_fail "remove missing asset" "not_found" "$PY" "$SCRIPTS/assets.py" remove ghost.png

# ===========================================================================
section "templates"
OUT="$(run "$SCRIPTS/templates.py" list)"
check "themes present" "$(printf '%s' "$OUT" | jqv "len(d['data']['themes']) >= 5")" "True"
check "demos present" "$(printf '%s' "$OUT" | jqv "'report' in d['data']['demos']")" "True"
OUT="$(run "$SCRIPTS/templates.py" show report)"
check "show theme kind" "$(printf '%s' "$OUT" | jqv "d['data']['kind']")" "theme"
check "theme palette merged" "$(printf '%s' "$OUT" | jqv "'accent' in d['data']['palette']")" "True"
expect_fail "show unknown template" "not_found" "$PY" "$SCRIPTS/templates.py" show ghost
OUT="$(run "$SCRIPTS/templates.py" spec report --out "$TMPDIR_SMOKE/report_spec.json")"
check "spec written" "$(printf '%s' "$OUT" | jqv "d['data']['bytes'] > 0")" "True"

if [ "$HAVE_RL" -eq 0 ]; then
  printf '\nSKIP: reportlab is not installed; skipping render sections (pip install -r requirements.txt)\n'
else
  # =========================================================================
  section "render"
  OUT="$(run "$SCRIPTS/render.py" render --spec "$TMPDIR_SMOKE/report_spec.json" --out "$TMPDIR_SMOKE/report.pdf")"
  check "render ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
  check "render has pages" "$(printf '%s' "$OUT" | jqv "d['data']['pages'] >= 2")" "True"
  check "render sha256 length" "$(printf '%s' "$OUT" | jqv "len(d['data']['sha256'])")" "64"
  check "render file exists" "$(test -s "$TMPDIR_SMOKE/report.pdf" && echo yes)" "yes"
  expect_fail "render conflict" "conflict" "$PY" "$SCRIPTS/render.py" render --spec "$TMPDIR_SMOKE/report_spec.json" --out "$TMPDIR_SMOKE/report.pdf"

  OUT="$(run "$SCRIPTS/render.py" render --doc invoice-2 --var number=INV-9 --var client=Northwind --out "$TMPDIR_SMOKE/invoice.pdf" --force)"
  check "render doc recipe" "$(printf '%s' "$OUT" | jqv "d['data']['recipe']")" "document"
  check "render doc name" "$(printf '%s' "$OUT" | jqv "d['data']['document']")" "invoice-2"
  check "render recorded" "$(printf '%s' "$OUT" | jqv "'render_id' in d['data']")" "True"

  OUT="$(run "$SCRIPTS/render.py" check --spec "$TMPDIR_SMOKE/report_spec.json" --strict)"
  check "check strict valid" "$(printf '%s' "$OUT" | jqv "d['data']['valid']")" "True"
  check "check strict flowables" "$(printf '%s' "$OUT" | jqv "d['data']['flowables'] > 0")" "True"

  OUT="$(run "$SCRIPTS/templates.py" demo invoice --out "$TMPDIR_SMOKE/demo_invoice.pdf")"
  check "demo pages" "$(printf '%s' "$OUT" | jqv "d['data']['pages'] >= 1")" "True"

  OUT="$(run "$SCRIPTS/render.py" from-markdown --in "$TMPDIR_SMOKE/guide.md" --out "$TMPDIR_SMOKE/guide.pdf" --toc --header "Field Guide")"
  check "markdown blocks" "$(printf '%s' "$OUT" | jqv "d['data']['blocks'] >= 5")" "True"
  check "markdown pages" "$(printf '%s' "$OUT" | jqv "d['data']['pages'] >= 1")" "True"

  OUT="$(run "$SCRIPTS/render.py" render --spec "$TMPDIR_SMOKE/secure_spec.json" --out "$TMPDIR_SMOKE/secure.pdf" --force)"
  check "encrypted render" "$(printf '%s' "$OUT" | jqv "d['data']['pages']")" "1"

  OUT="$(run "$SCRIPTS/render.py" render --spec "$TMPDIR_SMOKE/layout_spec.json" --out "$TMPDIR_SMOKE/layout.pdf" --force)"
  check "layout render" "$(printf '%s' "$OUT" | jqv "d['data']['pages'] >= 2")" "True"
  check "tall image fits" "$(printf '%s' "$OUT" | jqv "len(d['data']['warnings'])")" "0"

  OUT="$(run "$SCRIPTS/render.py" render --spec "$TMPDIR_SMOKE/sections_spec.json" --out "$TMPDIR_SMOKE/sections.pdf" --force)"
  check "section render" "$(printf '%s' "$OUT" | jqv "d['data']['pages'] >= 4")" "True"

  if have_pypdf; then
    OUT="$(run "$SCRIPTS/reports.py" inspect "$TMPDIR_SMOKE/report.pdf")"
    check "inspect pages" "$(printf '%s' "$OUT" | jqv "d['data']['pages'] >= 2")" "True"
    OUT="$(run "$SCRIPTS/reports.py" inspect "$TMPDIR_SMOKE/secure.pdf")"
    check "inspect encrypted" "$(printf '%s' "$OUT" | jqv "d['data']['encrypted']")" "True"
    OUT="$(run "$SCRIPTS/reports.py" inspect "$TMPDIR_SMOKE/secure.pdf" --password open-sesame)"
    check "inspect unlocked" "$(printf '%s' "$OUT" | jqv "d['data']['readable']")" "True"
    "$PY" - "$TMPDIR_SMOKE/layout.pdf" <<'PY' && pass || fail "landscape page size not detected"
import sys
from pypdf import PdfReader
widths = [(float(p.mediabox.width), float(p.mediabox.height)) for p in PdfReader(sys.argv[1]).pages]
if not any(w > h for w, h in widths):
    raise SystemExit(1)
PY
    "$PY" - "$TMPDIR_SMOKE/layout.pdf" <<'PY' && pass || fail "header/footer not placed in the page margins"
import sys
from pypdf import PdfReader

reader = PdfReader(sys.argv[1])
footer_ok = header_ok = False
for page in reader.pages:
    height = float(page.mediabox.height)
    seen = []

    def visit(text, cm, tm, font, size, seen=seen):
        token = text.strip()
        if token:
            seen.append((token, tm[5]))

    page.extract_text(visitor_text=visit)
    for token, y in seen:
        if token.startswith("Page ") and y < 60:  # ~0.5in from the bottom trim
            footer_ok = True
        if token == "Layout" and y > height - 60:  # ~0.5in from the top trim
            header_ok = True
if not (footer_ok and header_ok):
    raise SystemExit(1)
PY
    "$PY" - "$TMPDIR_SMOKE/sections.pdf" <<'PY' && pass || fail "TOC not flush left or sections not starting on their own pages"
import sys
from pypdf import PdfReader
from pypdf.generic import IndirectObject


def tokens(page):
    out = []

    def visit(text, cm, tm, font, size):
        token = text.strip()
        if token:
            out.append((token, tm[4]))

    page.extract_text(visitor_text=visit)
    return out


reader = PdfReader(sys.argv[1])
pages = reader.pages
toc = tokens(pages[0])


def x_of(name):
    values = [x for token, x in toc if token == name]
    if len(values) != 1:
        raise SystemExit(1)
    return values[0]


base = x_of("Contents")
# Level-1 entries share the title's left edge; level 2 is indented from it.
for name in ("Alpha", "Beta", "Gamma"):
    if abs(x_of(name) - base) > 0.6:
        raise SystemExit(1)
if x_of("Alpha sub") - base < 8:
    raise SystemExit(1)

# Every level-1 section starts on its own page and no page is blank.
expected = (("Alpha", ("Beta", "Gamma")), ("Beta", ("Alpha", "Gamma")), ("Gamma", ("Alpha", "Beta")))
for index, (own, others) in enumerate(expected, start=1):
    names = {token for token, x in tokens(pages[index])}
    if not names or own not in names or any(other in names for other in others):
        raise SystemExit(1)

# TOC links and outline entries must resolve to the section pages, never back
# to the TOC page itself.
page_index = {page.indirect_reference.idnum: i for i, page in enumerate(pages)}
for annot in pages[0].get("/Annots") or []:
    dest = annot.get_object().get("/Dest")
    if isinstance(dest, list) and dest and isinstance(dest[0], IndirectObject):
        if page_index.get(dest[0].idnum) in (None, 0):
            raise SystemExit(1)


def outline_pages(items):
    for item in items:
        if isinstance(item, list):
            yield from outline_pages(item)
        else:
            yield reader.get_destination_page_number(item)


if not reader.outline or any(page == 0 for page in outline_pages(reader.outline)):
    raise SystemExit(1)
PY
  else
    printf 'SKIP: pypdf not installed; skipping PDF inspection checks\n'
  fi
fi

# ===========================================================================
section "reports"
OUT="$(run "$SCRIPTS/reports.py" history --limit 5)"
check "history read only" "$(printf '%s' "$OUT" | jqv "d['data']['read_only']")" "True"
if [ "$HAVE_RL" -eq 1 ]; then
  check "history count" "$(printf '%s' "$OUT" | jqv "d['data']['count'] >= 1")" "True"
  RID="$(printf '%s' "$OUT" | jqv "d['data']['renders'][0]['id']")"
  OUT="$(run "$SCRIPTS/reports.py" show "$RID")"
  check "show render id" "$(printf '%s' "$OUT" | jqv "d['data']['id']")" "$RID"
else
  printf 'SKIP: reportlab not installed; no renders recorded\n'
fi
OUT="$(run "$SCRIPTS/reports.py" storage)"
check "storage documents" "$(printf '%s' "$OUT" | jqv "d['data']['documents'] >= 1")" "True"
OUT="$(run "$SCRIPTS/reports.py" stats)"
check "stats read only" "$(printf '%s' "$OUT" | jqv "d['data']['read_only']")" "True"

# ===========================================================================
section "errors"
printf '%s' '{"content":[{"type":"bogus"}]}' > "$TMPDIR_SMOKE/bad_block.json"
expect_fail "unknown block type" "invalid_spec" "$PY" "$SCRIPTS/render.py" check --spec "$TMPDIR_SMOKE/bad_block.json"
printf '%s' '{"spec_version":99,"content":[]}' > "$TMPDIR_SMOKE/bad_version.json"
expect_fail "future spec version" "invalid_spec" "$PY" "$SCRIPTS/render.py" check --spec "$TMPDIR_SMOKE/bad_version.json"
printf '%s' '{"content":[{"type":"paragraph","text":"x","color":"notacolor"}]}' > "$TMPDIR_SMOKE/bad_color.json"
if [ "$HAVE_RL" -eq 1 ]; then
  expect_fail "invalid color" "invalid_input" "$PY" "$SCRIPTS/render.py" check --spec "$TMPDIR_SMOKE/bad_color.json" --strict
  printf '%s' '{"content":[{"type":"image","src":"missing.png"}]}' > "$TMPDIR_SMOKE/bad_image.json"
  expect_fail "missing image" "not_found" "$PY" "$SCRIPTS/render.py" render --spec "$TMPDIR_SMOKE/bad_image.json" --out "$TMPDIR_SMOKE/bad.pdf"
else
  printf 'SKIP: reportlab not installed; skipping strict validation checks\n'
fi
expect_fail "render unknown doc" "not_found" "$PY" "$SCRIPTS/render.py" render --doc ghost
expect_fail "missing spec file" "not_found" "$PY" "$SCRIPTS/render.py" check --spec "$TMPDIR_SMOKE/none.json"

# ===========================================================================
section "scheduling"
for target in generic nanobot hermes claude codex kilo crontab systemd launchd; do
  OUT="$(run "$SCRIPTS/render.py" schedule-hint --doc invoice-2 --out "$TMPDIR_SMOKE/sched.pdf" --target "$target" --path-mode abs --tz Asia/Jakarta --at-time 07:30 --name pdf-job)"
  check "$target ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
  check "$target installs nothing" "$(printf '%s' "$OUT" | jqv "d['data']['installs_nothing']")" "True"
  check "$target cron expr" "$(printf '%s' "$OUT" | jqv "d['data']['cron_expr']")" "30 7 * * *"
  check "$target store" "$(printf '%s' "$OUT" | jqv "'pdf-creator.db' in d['data']['store']")" "True"
  check "$target has post" "$(printf '%s' "$OUT" | jqv "any(c['step']=='post' for c in d['data']['commands'])")" "True"
done

OUT="$(run "$SCRIPTS/render.py" schedule-hint --doc invoice-2 --target nanobot --path-mode abs --name pdf-job)"
check "nanobot message prefix" "$(printf '%s' "$OUT" | jqv "d['data']['message'].startswith('\$pdf-creator')")" "True"
check "nanobot crontool keys" "$(printf '%s' "$OUT" | jqv "sorted(d['data']['cron_tool'].keys())")" "['action', 'cron_expr', 'message', 'name', 'tz']"
OUT="$(run "$SCRIPTS/render.py" schedule-hint --doc invoice-2 --target hermes --path-mode abs --name pdf-job)"
check "hermes skills" "$(printf '%s' "$OUT" | jqv "d['data']['skills']")" "['pdf-creator']"

for action in disable enable remove list; do
  OUT="$(run "$SCRIPTS/render.py" schedule-hint --doc invoice-2 --target nanobot --action "$action" --job pdf-job --name pdf-job)"
  check "action $action" "$(printf '%s' "$OUT" | jqv "d['data']['action']")" "$action"
  check "action $action installs nothing" "$(printf '%s' "$OUT" | jqv "d['data']['installs_nothing']")" "True"
  check "action $action routes" "$(printf '%s' "$OUT" | jqv "isinstance(d['data']['routes'], list)")" "True"
done

OUT="$(run "$SCRIPTS/render.py" schedule-hint --doc invoice-2 --target launchd --path-mode abs --tz UTC --name pdf-job)"
printf '%s' "$OUT" | "$PY" -c 'import json,sys,plistlib
d=json.load(sys.stdin)["data"]
plistlib.loads(d["install"]["files"]["com.pdf-creator.render.plist"].encode())' && pass || fail "launchd plist not valid"

OUT="$(run "$SCRIPTS/render.py" schedule-hint --doc invoice-2 --out "$TMPDIR_SMOKE/sched.pdf" --target generic --path-mode abs)"
REPORT_CMD="$(printf '%s' "$OUT" | jqv "[c['command'] for c in d['data']['commands'] if c['step']=='report'][0]")"
REPORT_CMD="${REPORT_CMD/#python3 /$PY }"
FIRST="$(eval "$REPORT_CMD" 2>/dev/null)"; rc=$?
check "emitted report exit" "$rc" "0"
SECOND="$(eval "$REPORT_CMD" 2>/dev/null)"
check "emitted report idempotent" "$([ "$FIRST" = "$SECOND" ] && echo yes || echo no)" "yes"

if [ "$HAVE_RL" -eq 1 ]; then
  POST_CMD="$(printf '%s' "$OUT" | jqv "[c['command'] for c in d['data']['commands'] if c['step']=='post'][0]")"
  POST_CMD="${POST_CMD/#python3 /$PY }"
  eval "$POST_CMD" >/dev/null 2>&1
  check "emitted post command" "$(test -s "$TMPDIR_SMOKE/sched.pdf" && echo yes || echo no)" "yes"
fi

# ===========================================================================
section "portability"
SKILL_BODY="$TMPDIR_SMOKE/skill_body.md"
"$PY" -c 'import sys
parts=open(sys.argv[1], encoding="utf-8").read().split("---", 2)
open(sys.argv[2], "w", encoding="utf-8").write(parts[2] if len(parts) > 2 else "")' \
  "$SKILL/SKILL.md" "$SKILL_BODY"
LEAKS="$(grep -RIl -e 'nanobot' -e 'hermes' -e 'claude' -e 'codex' -e 'kilo' -e '\$pdf-creator' \
  "$SKILL_BODY" "$SKILL/references" "$SKILL/scripts" \
  | grep -v -e "$SKILL/references/scheduling.md" -e "$SKILL/scripts/render.py" -e "$SKILL/scripts/__pycache__" || true)"
if [ -z "$LEAKS" ]; then pass; else fail "host tokens leaked into: $LEAKS"; fi
grep -q 'TODO' "$SKILL/SKILL.md" && fail "SKILL.md contains TODO" || pass
STRAY="$(find "$SKILL" -maxdepth 1 -mindepth 1 ! -name SKILL.md ! -name scripts ! -name references ! -name assets ! -name README.md ! -name LICENSE ! -name .gitignore ! -name requirements.txt ! -name tests)"
[ -z "$STRAY" ] && pass || fail "stray files in skill root: $STRAY"
for helper in _lib _engine _engine_blocks _engine_blocks2 _rl _themes _markdown; do
  [ -x "$SCRIPTS/$helper.py" ] && fail "$helper.py should not be executable" || pass
done
for entry in init settings documents assets templates render reports; do
  [ -x "$SCRIPTS/$entry.py" ] && pass || fail "$entry.py is not executable"
done

# ===========================================================================
printf '\n========================================\n'
printf 'passed: %d   failed: %d\n' "$PASS" "$FAIL"
if [ "$FAIL" -ne 0 ]; then exit 1; fi
echo "smoke test OK"
