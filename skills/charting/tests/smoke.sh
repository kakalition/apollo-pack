#!/usr/bin/env bash
# End-to-end smoke test for the charting skill.
#
# Runs every script and verb against throwaway data roots and checks the JSON
# envelope, the state, the chart library, palettes/themes, validation, PNG
# introspection, the scheduler artifact matrix (including executing the emitted
# report command twice), error handling, and portability. Every fixture is
# generated at run time, so nothing binary is committed. Rendering sections are
# skipped unless Node, the esbuild bundle, and Chromium are all present; the
# state, library, theme, validation, and report verbs still run on a bare host.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILL="$ROOT"
SCRIPTS="$SKILL/scripts"
PY="${PY:-python3}"
export PYTHONWARNINGS="ignore"

PASS=0
FAIL=0
TMPDIR_SMOKE="$(mktemp -d "${TMPDIR:-/tmp}/scc-smoke.XXXXXX")"
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

have_node() { command -v node >/dev/null 2>&1; }
have_bundle() { [ -f "$SCRIPTS/vendor/chart-bundle.js" ]; }
have_chromium() {
  local dirs=("$HOME/Library/Caches/ms-playwright" "$HOME/.cache/ms-playwright" "$HOME/AppData/Local/ms-playwright")
  if [ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ] && [ "$PLAYWRIGHT_BROWSERS_PATH" != "0" ]; then
    dirs=("$PLAYWRIGHT_BROWSERS_PATH")
  fi
  local dir
  for dir in "${dirs[@]}"; do
    if compgen -G "$dir/chromium-*" >/dev/null 2>&1; then return 0; fi
  done
  return 1
}

HAVE_RENDER=0
if have_node && have_bundle && have_chromium; then HAVE_RENDER=1; fi

unset CHARTING_HOME CHARTING_THEME CHARTING_PALETTE \
  CHARTING_WIDTH CHARTING_HEIGHT CHARTING_SCALE \
  CHARTING_GRID CHARTING_LEGEND CHARTING_OUTPUT_DIR 2>/dev/null || true

export CHARTING_HOME="$TMPDIR_SMOKE/home"

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

(base / "fixture.png").write_bytes(png(64, 32, (124, 58, 237)))
(base / "bad_family.json").write_text('{"spec_version":1,"chart":"wat"}\n', encoding="utf-8")
(base / "no_x.json").write_text(
    '{"spec_version":1,"chart":"bar","data":[{"m":"A","v":1}],"series":[{"key":"v"}]}\n', encoding="utf-8")
(base / "bad_scale.json").write_text(
    '{"spec_version":1,"chart":"bar","scale":9,"data":[{"m":"A","v":1}],"x":{"key":"m"}}\n', encoding="utf-8")
(base / "bad_version.json").write_text('{"spec_version":99,"chart":"bar"}\n', encoding="utf-8")
(base / "missing_series.json").write_text(
    '{"spec_version":1,"chart":"bar","data":[{"m":"A","v":1}],"x":{"key":"m"},"series":[{"key":"ghost"}]}\n',
    encoding="utf-8")
(base / "custom.json").write_text(
    '{"spec_version":1,"chart":"bar","title":"Custom {{who}}","data":[{"m":"A","v":3},{"m":"B","v":5}],'
    '"x":{"key":"m"},"series":[{"key":"v","label":"Value"}],"palette":["#7c3aed","#22d3ee"],'
    '"width":400,"height":260,"scale":1}\n', encoding="utf-8")
PY

# ===========================================================================
section "init / settings"
OUT="$(run "$SCRIPTS/init.py" init)"
check "init ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
check "init schema" "$(printf '%s' "$OUT" | jqv "d['data']['schema_version']")" "1"
check "init first run" "$(printf '%s' "$OUT" | jqv "d['data']['already_initialized']")" "False"
check "init dependency keys" "$(printf '%s' "$OUT" | jqv "sorted(d['data']['dependencies'].keys())")" "['bundle', 'chromium', 'node', 'npm', 'playwright']"
OUT="$(run "$SCRIPTS/init.py" init)"
check "init idempotent" "$(printf '%s' "$OUT" | jqv "d['data']['already_initialized']")" "True"

OUT="$(run "$SCRIPTS/settings.py" show)"
check "settings default theme" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['theme']")" "light"
check "settings default palette" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['palette']")" "default"
OUT="$(run "$SCRIPTS/settings.py" set --theme dark --palette blue --width 800 --height 500 --scale 1 --grid off --legend right)"
check "settings set theme" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['theme']")" "dark"
check "settings set width" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['width']")" "800"
OUT="$(run "$SCRIPTS/settings.py" get --key legend)"
check "settings get" "$(printf '%s' "$OUT" | jqv "d['data']['value']")" "right"
run "$SCRIPTS/settings.py" set --theme light --palette default --width 720 --height 420 --scale 2 --grid on --legend bottom >/dev/null
expect_fail "settings set with no flags" "invalid_input" "$PY" "$SCRIPTS/settings.py" set
expect_fail "settings bad palette" "invalid_input" "$PY" "$SCRIPTS/settings.py" set --palette rainbow

# ===========================================================================
section "charts"
run "$SCRIPTS/themes.py" spec bar --out "$TMPDIR_SMOKE/bar.json" >/dev/null
OUT="$(run "$SCRIPTS/charts.py" save --name revenue --spec "$TMPDIR_SMOKE/bar.json" --tags finance,demo)"
check "save created" "$(printf '%s' "$OUT" | jqv "d['data']['created']")" "True"
check "save family" "$(printf '%s' "$OUT" | jqv "d['data']['family']")" "bar"
expect_fail "save duplicate" "conflict" "$PY" "$SCRIPTS/charts.py" save --name revenue --spec "$TMPDIR_SMOKE/bar.json"
OUT="$(run "$SCRIPTS/charts.py" save --name revenue --spec "$TMPDIR_SMOKE/bar.json" --force)"
check "save overwrite" "$(printf '%s' "$OUT" | jqv "d['data']['overwritten']")" "True"
OUT="$(run "$SCRIPTS/charts.py" list)"
check "list count" "$(printf '%s' "$OUT" | jqv "d['data']['count']")" "1"
OUT="$(run "$SCRIPTS/charts.py" list --family bar)"
check "list by family" "$(printf '%s' "$OUT" | jqv "d['data']['count']")" "1"
OUT="$(run "$SCRIPTS/charts.py" show revenue)"
check "show family" "$(printf '%s' "$OUT" | jqv "d['data']['family']")" "bar"
check "show points" "$(printf '%s' "$OUT" | jqv "d['data']['points']")" "6"
OUT="$(run "$SCRIPTS/charts.py" rename revenue revenue-2)"
check "rename" "$(printf '%s' "$OUT" | jqv "d['data']['name']")" "revenue-2"
OUT="$(run "$SCRIPTS/charts.py" duplicate revenue-2 revenue-copy)"
check "duplicate" "$(printf '%s' "$OUT" | jqv "d['data']['name']")" "revenue-copy"
OUT="$(run "$SCRIPTS/charts.py" export revenue-2 --out "$TMPDIR_SMOKE/exported.json")"
check "export file" "$(printf '%s' "$OUT" | jqv "d['data']['bytes'] > 0")" "True"
expect_fail "delete without yes" "invalid_input" "$PY" "$SCRIPTS/charts.py" delete revenue-copy
run "$SCRIPTS/charts.py" delete revenue-copy --yes >/dev/null
OUT="$(run "$SCRIPTS/charts.py" list)"
check "list after delete" "$(printf '%s' "$OUT" | jqv "d['data']['count']")" "1"
expect_fail "show unknown chart" "not_found" "$PY" "$SCRIPTS/charts.py" show ghost

# ===========================================================================
section "themes"
OUT="$(run "$SCRIPTS/themes.py" list)"
check "palettes present" "$(printf '%s' "$OUT" | jqv "len(d['data']['palettes']) >= 7")" "True"
check "themes present" "$(printf '%s' "$OUT" | jqv "sorted(t['name'] for t in d['data']['themes'])")" "['dark', 'light']"
check "demos present" "$(printf '%s' "$OUT" | jqv "sorted(d['data']['demos'])")" "['area', 'bar', 'donut', 'line', 'pie', 'radar', 'radial']"
OUT="$(run "$SCRIPTS/themes.py" show default)"
check "show palette kind" "$(printf '%s' "$OUT" | jqv "d['data']['kind']")" "palette"
check "show palette colors" "$(printf '%s' "$OUT" | jqv "len(d['data']['colors'])")" "5"
OUT="$(run "$SCRIPTS/themes.py" show dark --kind theme)"
check "show theme tokens" "$(printf '%s' "$OUT" | jqv "'--chart-1' in d['data']['tokens']")" "True"
OUT="$(run "$SCRIPTS/themes.py" show bar --kind demo)"
check "show demo kind" "$(printf '%s' "$OUT" | jqv "d['data']['kind']")" "demo"
expect_fail "show unknown theme" "not_found" "$PY" "$SCRIPTS/themes.py" show ghost
OUT="$(run "$SCRIPTS/themes.py" spec radar --out "$TMPDIR_SMOKE/radar.json")"
check "spec written" "$(printf '%s' "$OUT" | jqv "d['data']['bytes'] > 0")" "True"

# ===========================================================================
section "validation"
OUT="$(run "$SCRIPTS/render.py" check --spec "$TMPDIR_SMOKE/bar.json")"
check "check valid" "$(printf '%s' "$OUT" | jqv "d['data']['valid']")" "True"
check "check family" "$(printf '%s' "$OUT" | jqv "d['data']['family']")" "bar"
check "check layout" "$(printf '%s' "$OUT" | jqv "d['data']['layout']['plot_width'] > 0")" "True"
expect_fail "unknown family" "invalid_spec" "$PY" "$SCRIPTS/render.py" check --spec "$TMPDIR_SMOKE/bad_family.json"
expect_fail "missing x.key" "invalid_spec" "$PY" "$SCRIPTS/render.py" check --spec "$TMPDIR_SMOKE/no_x.json"
expect_fail "invalid scale" "invalid_spec" "$PY" "$SCRIPTS/render.py" check --spec "$TMPDIR_SMOKE/bad_scale.json"
expect_fail "future spec version" "invalid_spec" "$PY" "$SCRIPTS/render.py" check --spec "$TMPDIR_SMOKE/bad_version.json"
expect_fail "series key absent" "invalid_spec" "$PY" "$SCRIPTS/render.py" check --spec "$TMPDIR_SMOKE/missing_series.json"
expect_fail "missing spec file" "not_found" "$PY" "$SCRIPTS/render.py" check --spec "$TMPDIR_SMOKE/none.json"

# ===========================================================================
section "component"
OUT="$(run "$SCRIPTS/render.py" component --spec "$TMPDIR_SMOKE/bar.json")"
COMPONENT="$(printf '%s' "$OUT" | jqv "d['data']['component']")"
check "component imports recharts" "$(printf '%s' "$COMPONENT" | grep -q 'from "recharts"' && echo yes || echo no)" "yes"
check "component names BarChart" "$(printf '%s' "$COMPONENT" | grep -q '<BarChart' && echo yes || echo no)" "yes"
OUT="$(run "$SCRIPTS/render.py" component --doc revenue-2 --out "$TMPDIR_SMOKE/chart.jsx")"
check "component file" "$(printf '%s' "$OUT" | jqv "d['data']['bytes'] > 0")" "True"

# ===========================================================================
section "reports"
OUT="$(run "$SCRIPTS/reports.py" inspect "$TMPDIR_SMOKE/fixture.png")"
check "inspect width" "$(printf '%s' "$OUT" | jqv "d['data']['width']")" "64"
check "inspect height" "$(printf '%s' "$OUT" | jqv "d['data']['height']")" "32"
check "inspect color" "$(printf '%s' "$OUT" | jqv "d['data']['color_type_name']")" "truecolor"
OUT="$(run "$SCRIPTS/reports.py" history --limit 5)"
check "history read only" "$(printf '%s' "$OUT" | jqv "d['data']['read_only']")" "True"
OUT="$(run "$SCRIPTS/reports.py" storage)"
check "storage charts" "$(printf '%s' "$OUT" | jqv "d['data']['charts'] >= 1")" "True"
OUT="$(run "$SCRIPTS/reports.py" stats)"
check "stats read only" "$(printf '%s' "$OUT" | jqv "d['data']['read_only']")" "True"
expect_fail "inspect missing png" "not_found" "$PY" "$SCRIPTS/reports.py" inspect "$TMPDIR_SMOKE/none.png"
printf 'not a png' > "$TMPDIR_SMOKE/not.png"
expect_fail "inspect non png" "invalid_png" "$PY" "$SCRIPTS/reports.py" inspect "$TMPDIR_SMOKE/not.png"

# ===========================================================================
if [ "$HAVE_RENDER" -eq 0 ]; then
  printf '\nSKIP: Node, the chart bundle, and Chromium are all required; rendering sections skipped\n'
  printf 'SKIP: run: npm ci --prefix %s && node %s/scripts/build.mjs && npx --prefix %s playwright install chromium\n' "$SKILL" "$SKILL" "$SKILL"
else
  # =========================================================================
  section "render"
  if [ -d "$SKILL/node_modules/esbuild" ]; then
    OUT="$(node "$SCRIPTS/build.mjs")"
    check "bundle rebuilt from boot source" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
  else
    printf 'SKIP: esbuild not installed; using the existing prebuilt bundle\n'
  fi
  for family in bar line area pie donut radar radial; do
    run "$SCRIPTS/themes.py" spec "$family" --out "$TMPDIR_SMOKE/$family.json" >/dev/null
    OUT="$(run "$SCRIPTS/render.py" render --spec "$TMPDIR_SMOKE/$family.json" --out "$TMPDIR_SMOKE/$family.png" --force)"
    check "$family render ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
    check "$family family" "$(printf '%s' "$OUT" | jqv "d['data']['family']")" "$family"
    check "$family dims" "$(printf '%s' "$OUT" | jqv "d['data']['width'] == 1440 and d['data']['height'] == 840")" "True"
    check "$family png magic" "$(printf '%s' "$OUT" | jqv "d['data']['sha256'] and d['data']['bytes'] > 0")" "True"
    MAGIC="$("$PY" -c 'import sys; print(open(sys.argv[1],"rb").read(8) == b"\x89PNG\r\n\x1a\n")' "$TMPDIR_SMOKE/$family.png")"
    check "$family file is png" "$MAGIC" "True"
  done

  OUT="$(run "$SCRIPTS/render.py" render --spec "$TMPDIR_SMOKE/custom.json" --out "$TMPDIR_SMOKE/custom.png" --scale 1 --theme dark --transparent --var who=Northwind --force --keep-html --register --pdf-home "$TMPDIR_SMOKE/pdf-home")"
  check "custom scale" "$(printf '%s' "$OUT" | jqv "d['data']['scale']")" "1"
  check "custom theme" "$(printf '%s' "$OUT" | jqv "d['data']['theme']")" "dark"
  check "custom dims" "$(printf '%s' "$OUT" | jqv "d['data']['width'] == 400 and d['data']['height'] == 260")" "True"
  check "custom transparent" "$(printf '%s' "$OUT" | jqv "d['data']['background']")" "transparent"
  check "custom html kept" "$(printf '%s' "$OUT" | jqv "d['data']['html'] is not None")" "True"
  check "custom registered" "$(printf '%s' "$OUT" | jqv "d['data']['register']['asset']")" "custom.png"
  check "registered asset exists" "$(test -s "$TMPDIR_SMOKE/pdf-home/assets/custom.png" && echo yes)" "yes"
  expect_fail "render conflict" "conflict" "$PY" "$SCRIPTS/render.py" render --spec "$TMPDIR_SMOKE/custom.json" --out "$TMPDIR_SMOKE/custom.png"
  expect_fail "render unknown doc" "not_found" "$PY" "$SCRIPTS/render.py" render --doc ghost

  OUT="$(run "$SCRIPTS/render.py" check --spec "$TMPDIR_SMOKE/bar.json" --strict)"
  check "check strict renderable" "$(printf '%s' "$OUT" | jqv "d['data']['renderable']")" "True"

  OUT="$(run "$SCRIPTS/reports.py" inspect "$TMPDIR_SMOKE/custom.png")"
  check "inspect rendered png" "$(printf '%s' "$OUT" | jqv "d['data']['color_type_name']")" "truecolor-alpha"
  OUT="$(run "$SCRIPTS/reports.py" history --limit 20)"
  check "history recorded" "$(printf '%s' "$OUT" | jqv "d['data']['count'] >= 7")" "True"
  RID="$(printf '%s' "$OUT" | jqv "d['data']['renders'][0]['id']")"
  OUT="$(run "$SCRIPTS/reports.py" show "$RID")"
  check "show render id" "$(printf '%s' "$OUT" | jqv "d['data']['id']")" "$RID"

  OUT="$(run "$SCRIPTS/themes.py" demo donut --out "$TMPDIR_SMOKE/demo-donut.png")"
  check "demo render" "$(printf '%s' "$OUT" | jqv "d['data']['family']")" "donut"
fi

# ===========================================================================
section "scheduling"
for target in generic nanobot hermes claude codex kilo crontab systemd launchd; do
  OUT="$(run "$SCRIPTS/render.py" schedule-hint --doc revenue-2 --out "$TMPDIR_SMOKE/sched.png" --target "$target" --path-mode abs --tz Asia/Jakarta --at-time 07:30 --name chart-job)"
  check "$target ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
  check "$target installs nothing" "$(printf '%s' "$OUT" | jqv "d['data']['installs_nothing']")" "True"
  check "$target cron expr" "$(printf '%s' "$OUT" | jqv "d['data']['cron_expr']")" "30 7 * * *"
  check "$target store" "$(printf '%s' "$OUT" | jqv "'charting.db' in d['data']['store']")" "True"
  check "$target has post" "$(printf '%s' "$OUT" | jqv "any(c['step']=='post' for c in d['data']['commands'])")" "True"
done

OUT="$(run "$SCRIPTS/render.py" schedule-hint --doc revenue-2 --target nanobot --path-mode abs --name chart-job)"
check "nanobot message prefix" "$(printf '%s' "$OUT" | jqv "d['data']['message'].startswith('\$charting')")" "True"
check "nanobot crontool keys" "$(printf '%s' "$OUT" | jqv "sorted(d['data']['cron_tool'].keys())")" "['action', 'cron_expr', 'message', 'name', 'tz']"
OUT="$(run "$SCRIPTS/render.py" schedule-hint --doc revenue-2 --target hermes --path-mode abs --name chart-job)"
check "hermes skills" "$(printf '%s' "$OUT" | jqv "d['data']['skills']")" "['charting']"

for action in disable enable remove list; do
  OUT="$(run "$SCRIPTS/render.py" schedule-hint --doc revenue-2 --target nanobot --action "$action" --job chart-job --name chart-job)"
  check "action $action" "$(printf '%s' "$OUT" | jqv "d['data']['action']")" "$action"
  check "action $action installs nothing" "$(printf '%s' "$OUT" | jqv "d['data']['installs_nothing']")" "True"
  check "action $action routes" "$(printf '%s' "$OUT" | jqv "isinstance(d['data']['routes'], list)")" "True"
done

OUT="$(run "$SCRIPTS/render.py" schedule-hint --doc revenue-2 --target launchd --path-mode abs --tz UTC --name chart-job)"
printf '%s' "$OUT" | "$PY" -c 'import json,sys,plistlib
d=json.load(sys.stdin)["data"]
plistlib.loads(d["install"]["files"]["com.charting.render.plist"].encode())' && pass || fail "launchd plist not valid"

OUT="$(run "$SCRIPTS/render.py" schedule-hint --doc revenue-2 --out "$TMPDIR_SMOKE/sched.png" --target generic --path-mode abs)"
REPORT_CMD="$(printf '%s' "$OUT" | jqv "[c['command'] for c in d['data']['commands'] if c['step']=='report'][0]")"
REPORT_CMD="${REPORT_CMD/#python3 /$PY }"
FIRST="$(eval "$REPORT_CMD" 2>/dev/null)"; rc=$?
check "emitted report exit" "$rc" "0"
SECOND="$(eval "$REPORT_CMD" 2>/dev/null)"
check "emitted report idempotent" "$([ "$FIRST" = "$SECOND" ] && echo yes || echo no)" "yes"

if [ "$HAVE_RENDER" -eq 1 ]; then
  POST_CMD="$(printf '%s' "$OUT" | jqv "[c['command'] for c in d['data']['commands'] if c['step']=='post'][0]")"
  POST_CMD="${POST_CMD/#python3 /$PY }"
  eval "$POST_CMD" >/dev/null 2>&1
  check "emitted post command" "$(test -s "$TMPDIR_SMOKE/sched.png" && echo yes || echo no)" "yes"
fi

# ===========================================================================
section "portability"
SKILL_BODY="$TMPDIR_SMOKE/skill_body.md"
"$PY" -c 'import sys
parts=open(sys.argv[1], encoding="utf-8").read().split("---", 2)
open(sys.argv[2], "w", encoding="utf-8").write(parts[2] if len(parts) > 2 else "")' \
  "$SKILL/SKILL.md" "$SKILL_BODY"
LEAKS="$(grep -RIl -e 'nanobot' -e 'hermes' -e 'claude' -e 'codex' -e 'kilo' -e '\$charting' \
  "$SKILL_BODY" "$SKILL/references" "$SKILL/scripts" \
  | grep -v -e "$SKILL/references/scheduling.md" -e "$SKILL/scripts/render.py" -e "$SKILL/scripts/__pycache__" \
  | grep -v -e "$SKILL/scripts/vendor" -e "$SKILL/node_modules" || true)"
if [ -z "$LEAKS" ]; then pass; else fail "host tokens leaked into: $LEAKS"; fi
grep -q 'TODO' "$SKILL/SKILL.md" && fail "SKILL.md contains TODO" || pass
STRAY="$(find "$SKILL" -maxdepth 1 -mindepth 1 ! -name SKILL.md ! -name scripts ! -name references ! -name README.md ! -name LICENSE ! -name .gitignore ! -name requirements.txt ! -name tests ! -name package.json ! -name package-lock.json ! -name node_modules)"
[ -z "$STRAY" ] && pass || fail "stray files in skill root: $STRAY"
for helper in _lib.py _html.py; do
  [ -x "$SCRIPTS/$helper" ] && fail "$helper should not be executable" || pass
done
for entry in init settings charts themes render reports; do
  [ -x "$SCRIPTS/$entry.py" ] && pass || fail "$entry.py is not executable"
done
[ -x "$SCRIPTS/build.mjs" ] && fail "build.mjs should not be executable" || pass
[ -x "$SCRIPTS/screenshot.mjs" ] && fail "screenshot.mjs should not be executable" || pass

# ===========================================================================
printf '\n========================================\n'
printf 'passed: %d   failed: %d\n' "$PASS" "$FAIL"
if [ "$FAIL" -ne 0 ]; then exit 1; fi
echo "smoke test OK"
