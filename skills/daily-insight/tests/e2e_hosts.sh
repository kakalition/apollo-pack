#!/usr/bin/env bash
# Tier 2: hermetic host-compatibility E2E for the daily-insight skill.
#
# Validates that the same skill folder works under the discovery and invocation
# rules of Claude Code, Hermes, Codex, Kilo, nanobot/OpenClaw, and a generic
# host, using throwaway HOME / HERMES_HOME directories. No network. A real host
# loader is only exercised when its CLI is on PATH; otherwise the step prints
# SKIP and never fails.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILL="$ROOT"
SCRIPTS="$SKILL/scripts"
PY="${PY:-python3}"
export PYTHONWARNINGS="ignore"

PASS=0
FAIL=0
SKIPS=0
TMP="$(mktemp -d "${TMPDIR:-/tmp}/di-hosts.XXXXXX")"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

pass() { PASS=$((PASS + 1)); }
fail() { FAIL=$((FAIL + 1)); printf 'FAIL: %s\n' "$*" >&2; }
skip() { SKIPS=$((SKIPS + 1)); printf 'SKIP: %s\n' "$*"; }
section() { printf '\n== %s ==\n' "$*"; }
check() { if [ "$2" = "$3" ]; then pass; else fail "$1: expected [$3] got [$2]"; fi; }

jqv() { "$PY" -c 'import json,sys
d=json.load(sys.stdin)
print(eval(sys.argv[1]))' "$1"; }

if ! "$PY" -c 'import chromadb, pypdf, docx' >/dev/null 2>&1; then
  printf 'SKIP: tier 2 needs chromadb, pypdf, and python-docx (pip install -r requirements.txt)\n'
  exit 0
fi

# ===========================================================================
section "standard compliance (frontmatter)"
"$PY" - "$SKILL/SKILL.md" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
assert match, "SKILL.md has no YAML frontmatter block"
fm = match.group(1)
def field(name):
    m = re.search(r"^%s:\s*(.*)$" % re.escape(name), fm, re.M)
    return m.group(1).strip() if m else None
name = field("name")
desc = field("description")
assert name == "daily-insight", "name %r != folder name" % name
assert desc is not None, "missing description"
assert len(desc) <= 60, "description is %d chars (max 60): %r" % (len(desc), desc)
assert desc.rstrip('"').endswith("."), "description must end with a period"
for required in ("version", "author", "license", "platforms"):
    assert field(required) is not None, "missing %s" % required
platforms = field("platforms")
for os_name in ("linux", "macos", "windows"):
    assert os_name in platforms, "platforms is missing %s" % os_name
print("frontmatter OK")
PY
[ $? -eq 0 ] && pass || fail "frontmatter compliance"

# ===========================================================================
section "authoring audit"
"$PY" - "$SKILL/SKILL.md" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
body = text.split("---", 2)[2] if text.startswith("---") else text
order = ["# ", "## When to Use", "## Prerequisites", "## How to Run",
         "## Quick Reference", "## Procedure", "## Pitfalls", "## Verification"]
positions = []
for heading in order:
    idx = body.find(heading)
    assert idx != -1, "missing section %r" % heading
    positions.append(idx)
assert positions == sorted(positions), "sections are out of order"
author = re.search(r"^author:\s*(.*)$", text, re.M).group(1).strip()
assert author and "Agent" not in author.split(",")[0], "author must credit a human first"
assert "metadata:" in text and "hermes:" in text, "missing metadata.hermes"
assert re.search(r"category:\s*\S+", text), "missing metadata.hermes.category"
assert re.search(r"tags:\s*\[.+\]", text), "missing metadata.hermes.tags"
for tool in ("terminal", "read_file"):
    assert "`%s`" % tool in body, "prose should reference the %s tool in backticks" % tool
for banned in ("`grep`", "`cat`", "`sed`", "`awk`", "`find`", "`ls`"):
    assert banned not in body, "prose names wrapped shell utility %s" % banned
print("authoring OK")
PY
[ $? -eq 0 ] && pass || fail "authoring audit"

# ===========================================================================
section "cross-platform sanity"
BANNED="$(grep -RIn -e 'osascript' -e '/proc/' -e 'fcntl' -e 'termios' -e 'os\.setsid' \
  "$SCRIPTS" || true)"
if [ -z "$BANNED" ]; then pass; else fail "platform-bound primitives in scripts: $BANNED"; fi
"$PY" - "$SCRIPTS" <<'PY'
import ast, pathlib, sys
scripts = sorted(pathlib.Path(sys.argv[1]).glob("*.py"))
assert scripts, "no scripts found"
for path in scripts:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top not in ("fcntl", "termios", "osascript"), "%s imports %s" % (path.name, top)
print("imports OK")
PY
[ $? -eq 0 ] && pass || fail "cross-platform import scan"

# ===========================================================================
section "discovery + invocation per host"
HOSTS="claude hermes codex kilo nanobot generic"
for host in $HOSTS; do
  HOST_HOME="$TMP/$host/home"
  case "$host" in
    claude)   SKILLS="$HOST_HOME/.claude/skills" ;;
    hermes)   SKILLS="$HOST_HOME/.hermes/skills" ;;
    codex)    SKILLS="$HOST_HOME/.codex/skills" ;;
    kilo)     SKILLS="$HOST_HOME/.config/kilo/skills" ;;
    nanobot)  SKILLS="$HOST_HOME/.nanobot/workspace/skills" ;;
    generic)  SKILLS="$HOST_HOME/skills" ;;
  esac
  DATA="$TMP/$host/data"
  mkdir -p "$SKILLS"
  cp -R "$SKILL" "$SKILLS/daily-insight"
  INSTALLED="$SKILLS/daily-insight"
  OUT="$(env HOME="$HOST_HOME" HERMES_HOME="$HOST_HOME/.hermes" "$PY" "$INSTALLED/scripts/init.py" init --home "$DATA")"
  check "$host init ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
  check "$host command envelope" "$(printf '%s' "$OUT" | jqv "d['command']")" "init.init"
  OUT="$(env HOME="$HOST_HOME" "$PY" "$INSTALLED/scripts/ingest.py" ingest --text "Host check passage one." --material Probe --home "$DATA")"
  check "$host ingest ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
  OUT="$(env HOME="$HOST_HOME" "$PY" "$INSTALLED/scripts/insights.py" next --home "$DATA")"
  check "$host next delivered" "$(printf '%s' "$OUT" | jqv "d['data']['status']")" "delivered"
  # relative path form: run from inside the skill directory
  OUT="$(cd "$INSTALLED" && env HOME="$HOST_HOME" "$PY" scripts/reports.py stats --home "$DATA")"
  check "$host relative path ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
  # {skillDir} placeholder substitution, the form a substituting host would use
  OUT="$(env HOME="$HOST_HOME" "$PY" "${INSTALLED}/scripts/insights.py" due --home "$DATA")"
  check "$host placeholder path ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
done

# ===========================================================================
section "scheduler artifacts per host"
for host in $HOSTS; do
  TARGET="$host"
  DATA="$TMP/$host/data"
  OUT="$(env HOME="$TMP/$host/home" "$PY" "$SKILL/scripts/insights.py" schedule-hint --target "$TARGET" --home "$DATA")"
  check "$host hint ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
  check "$host hint installs nothing" "$(printf '%s' "$OUT" | jqv "d['data']['installs_nothing']")" "True"
  check "$host hint cron expr" "$(printf '%s' "$OUT" | jqv "len(d['data']['cron_expr'].split())")" "5"
  check "$host hint tz" "$(printf '%s' "$OUT" | jqv "isinstance(d['data']['tz'], str)")" "True"
done
OUT="$(env HOME="$TMP/nanobot/home" "$PY" "$SKILL/scripts/insights.py" schedule-hint --target nanobot --home "$TMP/nanobot/data")"
check "nanobot cron_tool action" "$(printf '%s' "$OUT" | jqv "d['data']['cron_tool']['action']")" "add"
OUT="$(env HOME="$TMP/hermes/home" "$PY" "$SKILL/scripts/insights.py" schedule-hint --target hermes --home "$TMP/hermes/data")"
check "hermes skills field" "$(printf '%s' "$OUT" | jqv "d['data']['skills']")" "['daily-insight']"
check "hermes script field" "$(printf '%s' "$OUT" | jqv "d['data']['script'].endswith('scripts/insights.py next --format json')")" "True"

# the emitted generic command is idempotent across two executions
DATA="$TMP/generic/data"
GEN="$(env HOME="$TMP/generic/home" "$PY" "$SKILL/scripts/insights.py" schedule-hint --target generic --path-mode abs --home "$DATA")"
RUNCMD="$(printf '%s' "$GEN" | jqv "d['data']['commands'][0]['command']")"
eval "$RUNCMD" >/dev/null 2>&1 || fail "host-emitted command failed"
eval "$RUNCMD" >/dev/null 2>&1 || fail "host-emitted command failed on second call"
OUT="$(env HOME="$TMP/generic/home" "$PY" "$SKILL/scripts/reports.py" stats --home "$DATA")"
check "host-emitted second call no double" "$(printf '%s' "$OUT" | jqv "d['data']['counts']['deliveries']")" "1"

# ===========================================================================
section "real host loaders (optional)"
for cli in claude hermes kilo codex nanobot; do
  if command -v "$cli" >/dev/null 2>&1; then
    skip "$cli is installed but its skill-list probe is host-specific and is not run here"
  else
    skip "$cli not on PATH"
  fi
done

# ===========================================================================
printf '\n========================================\n'
printf 'passed: %d   failed: %d   skipped: %d\n' "$PASS" "$FAIL" "$SKIPS"
if [ "$FAIL" -ne 0 ]; then exit 1; fi
echo "host e2e OK"
