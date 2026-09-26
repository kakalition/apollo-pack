#!/usr/bin/env bash
# End-to-end smoke test for the journal skill.
#
# Runs every script and verb against throwaway databases and checks output,
# hand-computed word counts and weekly summaries, FTS5 search and the LIKE
# fallback, reindexing on edit, scheduling artifacts (including executing them
# twice), output formats, and error handling. No network access; bash +
# python3 stdlib only.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILL="$ROOT"
SCRIPTS="$SKILL/scripts"
PY="${PY:-python3}"

PASS=0
FAIL=0
TMPDIR_SMOKE="$(mktemp -d "${TMPDIR:-/tmp}/journal-smoke.XXXXXX")"
cleanup() { rm -rf "$TMPDIR_SMOKE"; }
trap cleanup EXIT

pass() { PASS=$((PASS + 1)); }
fail() { FAIL=$((FAIL + 1)); printf 'FAIL: %s\n' "$*" >&2; }
section() { printf '\n== %s ==\n' "$*"; }

check() { # check DESC ACTUAL EXPECTED
  if [ "$2" = "$3" ]; then pass; else fail "$1: expected [$3] got [$2]"; fi
}

# jqv '<python expression using d>' reads JSON on stdin.
jqv() { "$PY" -c 'import json,sys
d=json.load(sys.stdin)
print(eval(sys.argv[1]))' "$1"; }

run() { "$PY" "$@"; }

# expect_fail DESC ERROR_CODE CMD...
expect_fail() {
  local desc="$1" code="$2"; shift 2
  local out rc
  out="$("$@" 2>/dev/null)"; rc=$?
  if [ "$rc" -eq 1 ]; then pass; else fail "$desc: expected exit 1, got $rc"; fi
  check "$desc code" "$(printf '%s' "$out" | jqv "d['error']['code']")" "$code"
}

# expect_usage DESC CMD...  (argparse errors exit 2)
expect_usage() {
  local desc="$1"; shift
  "$@" >/dev/null 2>&1; local rc=$?
  if [ "$rc" -eq 2 ]; then pass; else fail "$desc: expected exit 2, got $rc"; fi
}

unset JOURNAL_DB JOURNAL_TZ JOURNAL_WEEK_START JOURNAL_DEFAULT_LIMIT JOURNAL_REVIEW_PROMPT 2>/dev/null || true

# ===========================================================================
section "init / settings"
export JOURNAL_DB="$TMPDIR_SMOKE/main.db"
OUT="$(run "$SCRIPTS/init.py" init)"
check "init ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
check "init first run" "$(printf '%s' "$OUT" | jqv "d['data']['already_initialized']")" "False"
check "init schema version" "$(printf '%s' "$OUT" | jqv "d['data']['schema_version']")" "1"
check "init fts enabled" "$(printf '%s' "$OUT" | jqv "d['data']['fts_enabled']")" "True"
OUT="$(run "$SCRIPTS/init.py" init)"
check "init idempotent" "$(printf '%s' "$OUT" | jqv "d['data']['already_initialized']")" "True"

OUT="$(run "$SCRIPTS/settings.py" show)"
check "settings default tz" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['tz']")" "UTC"
check "settings default week start" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['week_start']")" "mon"
check "settings fts enabled" "$(printf '%s' "$OUT" | jqv "d['data']['fts_enabled']")" "True"

OUT="$(run "$SCRIPTS/settings.py" set --tz Asia/Jakarta --week-start sun --default-limit 5)"
check "settings set tz" "$(printf '%s' "$OUT" | jqv "d['data']['changed']['tz']")" "Asia/Jakarta"
check "settings set limit" "$(printf '%s' "$OUT" | jqv "d['data']['stored']['default_limit']")" "5"
OUT="$(run "$SCRIPTS/settings.py" get --key tz)"
check "settings get key" "$(printf '%s' "$OUT" | jqv "d['data']['value']")" "Asia/Jakarta"
OUT="$(env JOURNAL_TZ=Europe/Paris "$PY" "$SCRIPTS/settings.py" show)"
check "settings env override" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['tz']")" "Europe/Paris"
expect_fail "settings unknown key" "not_found" run "$SCRIPTS/settings.py" get --key nope
expect_fail "settings set no flags" "invalid_input" run "$SCRIPTS/settings.py" set
run "$SCRIPTS/settings.py" set --week-start mon --default-limit 20 >/dev/null

# ===========================================================================
section "entries add / list / show"
run "$SCRIPTS/entries.py" add --body "Met the deadline after a long week. The deadline felt heavy." --date 2026-01-05 --title Monday >/dev/null
OUT="$(run "$SCRIPTS/entries.py" add --body "Slept badly and missed the gym." --date 2026-01-06)"
check "add word count" "$(printf '%s' "$OUT" | jqv "d['data']['word_count']")" "6"
run "$SCRIPTS/entries.py" add --body "Good focus on the deadline research." --date 2026-01-06 >/dev/null
run "$SCRIPTS/entries.py" add --body "A quiet walk helped." --date 2026-01-07 >/dev/null

OUT="$(run "$SCRIPTS/entries.py" list)"
check "list count" "$(printf '%s' "$OUT" | jqv "len(d['data'])")" "4"
OUT="$(run "$SCRIPTS/entries.py" list --order asc)"
check "list order first" "$(printf '%s' "$OUT" | jqv "d['data'][0]['entry_date']")" "2026-01-05"
OUT="$(run "$SCRIPTS/entries.py" list --from 2026-01-06 --to 2026-01-07)"
check "list date range" "$(printf '%s' "$OUT" | jqv "len(d['data'])")" "3"
OUT="$(run "$SCRIPTS/entries.py" list --limit 1)"
check "list limit" "$(printf '%s' "$OUT" | jqv "len(d['data'])")" "1"
OUT="$(run "$SCRIPTS/entries.py" show 1)"
check "show body" "$(printf '%s' "$OUT" | jqv "d['data']['title']")" "Monday"
expect_fail "add empty body" "invalid_input" run "$SCRIPTS/entries.py" add --body "   "
expect_fail "add missing file" "not_found" run "$SCRIPTS/entries.py" add --file "$TMPDIR_SMOKE/nope.txt"
expect_fail "show unknown" "not_found" run "$SCRIPTS/entries.py" show 999
expect_fail "show non-numeric" "not_found" run "$SCRIPTS/entries.py" show abc
expect_fail "add bad date" "invalid_date" run "$SCRIPTS/entries.py" add --body x --date 2026-13-01

# ===========================================================================
section "word sources"
export JOURNAL_DB="$TMPDIR_SMOKE/words.db"
run "$SCRIPTS/init.py" init >/dev/null
printf 'one two three four five' > "$TMPDIR_SMOKE/body.txt"
OUT="$(run "$SCRIPTS/entries.py" add --file "$TMPDIR_SMOKE/body.txt" --date 2026-01-01)"
check "file word count" "$(printf '%s' "$OUT" | jqv "d['data']['word_count']")" "5"
OUT="$(printf 'alpha beta gamma' | "$PY" "$SCRIPTS/entries.py" add --date 2026-01-02)"
check "stdin word count" "$(printf '%s' "$OUT" | jqv "d['data']['word_count']")" "3"
check "stdin body stored" "$(printf '%s' "$OUT" | jqv "d['data']['body']")" "alpha beta gamma"

# ===========================================================================
section "search (FTS)"
export JOURNAL_DB="$TMPDIR_SMOKE/main.db"
OUT="$(run "$SCRIPTS/entries.py" search deadline)"
check "search fts flag" "$(printf '%s' "$OUT" | jqv "d['data']['fts']")" "True"
check "search count" "$(printf '%s' "$OUT" | jqv "d['data']['count']")" "2"
OUT="$(run "$SCRIPTS/entries.py" search gym)"
check "search single" "$(printf '%s' "$OUT" | jqv "d['data']['count']")" "1"
expect_fail "search no terms" "invalid_input" run "$SCRIPTS/entries.py" search "!!!"
expect_fail "search blank" "invalid_input" run "$SCRIPTS/entries.py" search ""

# ===========================================================================
section "week brief and stats"
# ISO week 2026-W02 is Monday 2026-01-05 .. Sunday 2026-01-11.
# 4 entries, 3 active days, 27 words, missing 08-11; "deadline" appears 3 times.
OUT="$(run "$SCRIPTS/reports.py" week --week 2026-W02)"
check "week from" "$(printf '%s' "$OUT" | jqv "d['data']['range']['from']")" "2026-01-05"
check "week label" "$(printf '%s' "$OUT" | jqv "d['data']['range']['week']")" "2026-W02"
check "week entry count" "$(printf '%s' "$OUT" | jqv "d['data']['entry_count']")" "4"
check "week days with entries" "$(printf '%s' "$OUT" | jqv "d['data']['days_with_entries']")" "3"
check "week missing days" "$(printf '%s' "$OUT" | jqv "len(d['data']['days_missing'])")" "4"
check "week total words" "$(printf '%s' "$OUT" | jqv "d['data']['total_words']")" "27"
check "week by day" "$(printf '%s' "$OUT" | jqv "[b for b in d['data']['by_day'] if b['date']=='2026-01-06'][0]['entries']")" "2"
check "week by day words" "$(printf '%s' "$OUT" | jqv "[b for b in d['data']['by_day'] if b['date']=='2026-01-06'][0]['words']")" "12"
check "week top term" "$(printf '%s' "$OUT" | jqv "d['data']['top_terms'][0]['term']")" "deadline"
check "week top term count" "$(printf '%s' "$OUT" | jqv "d['data']['top_terms'][0]['count']")" "3"
check "week top terms size" "$(printf '%s' "$OUT" | jqv "len(d['data']['top_terms'])")" "10"
check "week stops stopwords" "$(printf '%s' "$OUT" | jqv "'the' in [t['term'] for t in d['data']['top_terms']]")" "False"
check "week notable line" "$(printf '%s' "$OUT" | jqv "d['data']['notable_lines'][0]['text']")" "Good focus on the deadline research."
check "week read only" "$(printf '%s' "$OUT" | jqv "d['data']['read_only']")" "True"
check "week prompt present" "$(printf '%s' "$OUT" | jqv "len(d['data']['prompt']) > 0")" "True"

OUT="$(run "$SCRIPTS/reports.py" week --from 2026-01-05 --to 2026-01-11)"
check "week explicit range" "$(printf '%s' "$OUT" | jqv "d['data']['total_words']")" "27"
OUT="$(run "$SCRIPTS/reports.py" week)"
check "week default read only" "$(printf '%s' "$OUT" | jqv "d['data']['read_only']")" "True"
expect_fail "week partial range" "invalid_input" run "$SCRIPTS/reports.py" week --from 2026-01-05
expect_fail "week bad iso" "invalid_date" run "$SCRIPTS/reports.py" week --week 2026-W99

OUT="$(run "$SCRIPTS/reports.py" stats --from 2026-01-01 --to 2026-01-07)"
check "stats entries" "$(printf '%s' "$OUT" | jqv "d['data']['entry_count']")" "4"
check "stats words" "$(printf '%s' "$OUT" | jqv "d['data']['total_words']")" "27"
check "stats active days" "$(printf '%s' "$OUT" | jqv "d['data']['active_days']")" "3"
check "stats current run" "$(printf '%s' "$OUT" | jqv "d['data']['current_run']")" "3"
check "stats longest run" "$(printf '%s' "$OUT" | jqv "d['data']['longest_run']")" "3"
check "stats read only" "$(printf '%s' "$OUT" | jqv "d['data']['read_only']")" "True"

# ===========================================================================
section "edit / delete reindex"
OUT="$(run "$SCRIPTS/entries.py" edit 2 --body "Slept badly and skipped the gym session.")"
check "edit word count" "$(printf '%s' "$OUT" | jqv "d['data']['word_count']")" "7"
check "edit sets updated_at" "$(printf '%s' "$OUT" | jqv "d['data']['updated_at'] is not None")" "True"
OUT="$(run "$SCRIPTS/entries.py" search skipped)"
check "edit reindexes" "$(printf '%s' "$OUT" | jqv "d['data']['count']")" "1"
OUT="$(run "$SCRIPTS/entries.py" search missed)"
check "old term dropped" "$(printf '%s' "$OUT" | jqv "d['data']['count']")" "0"
expect_fail "edit with no fields" "invalid_input" run "$SCRIPTS/entries.py" edit 2

OUT="$(run "$SCRIPTS/entries.py" edit 1 --date 2026-01-08)"
check "edit date" "$(printf '%s' "$OUT" | jqv "d['data']['entry_date']")" "2026-01-08"
OUT="$(run "$SCRIPTS/entries.py" delete 4)"
check "delete ok" "$(printf '%s' "$OUT" | jqv "d['data']['deleted']")" "True"
OUT="$(run "$SCRIPTS/entries.py" search quiet)"
check "delete removes from search" "$(printf '%s' "$OUT" | jqv "d['data']['count']")" "0"
expect_fail "delete unknown" "not_found" run "$SCRIPTS/entries.py" delete 999

# ===========================================================================
section "search fallback (no FTS)"
export JOURNAL_DB="$TMPDIR_SMOKE/fallback.db"
OUT="$(run "$SCRIPTS/init.py" init --no-fts)"
check "fallback init" "$(printf '%s' "$OUT" | jqv "d['data']['fts_enabled']")" "False"
run "$SCRIPTS/entries.py" add --body "A hidden unicorn appears." --date 2026-01-05 >/dev/null
OUT="$(run "$SCRIPTS/entries.py" search unicorn)"
check "fallback search flag" "$(printf '%s' "$OUT" | jqv "d['data']['fts']")" "False"
check "fallback search count" "$(printf '%s' "$OUT" | jqv "d['data']['count']")" "1"
OUT="$(run "$SCRIPTS/settings.py" show)"
check "fallback settings" "$(printf '%s' "$OUT" | jqv "d['data']['fts_enabled']")" "False"
OUT="$(run "$SCRIPTS/init.py" init)"
check "re-init enables fts" "$(printf '%s' "$OUT" | jqv "d['data']['fts_enabled']")" "True"
OUT="$(run "$SCRIPTS/entries.py" search unicorn)"
check "rebuilt index finds row" "$(printf '%s' "$OUT" | jqv "d['data']['fts']")" "True"
check "rebuilt index count" "$(printf '%s' "$OUT" | jqv "d['data']['count']")" "1"

# ===========================================================================
section "formats, quiet, and errors"
export JOURNAL_DB="$TMPDIR_SMOKE/main.db"
OUT="$(run "$SCRIPTS/entries.py" list --format table)"
case "$OUT" in *"entry_date"*) pass;; *) fail "table output missing header";; esac
case "$OUT" in *'{'*) fail "table output should not be JSON";; *) pass;; esac
QUIET="$(run "$SCRIPTS/reports.py" stats --quiet)"
check "quiet suppresses output" "$QUIET" ""
expect_usage "unknown verb" run "$SCRIPTS/entries.py" bogus
expect_usage "missing positional" run "$SCRIPTS/entries.py" show

# ===========================================================================
section "scheduling artifacts"
for TARGET in generic nanobot hermes claude codex kilo crontab systemd launchd; do
  OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target "$TARGET")"
  check "hint $TARGET ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
  check "hint $TARGET installs nothing" "$(printf '%s' "$OUT" | jqv "d['data']['installs_nothing']")" "True"
  check "hint $TARGET read only" "$(printf '%s' "$OUT" | jqv "d['data']['read_only']")" "True"
done

OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target generic --path-mode relative)"
check "relative path mode" "$(printf '%s' "$OUT" | jqv "d['data']['commands'][0]['command'].startswith('python3 scripts/reports.py')")" "True"
OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target generic --path-mode skill)"
check "skill path mode" "$(printf '%s' "$OUT" | jqv "'{skillDir}/scripts/reports.py' in d['data']['commands'][0]['command']")" "True"
OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target crontab --path-mode abs)"
check "abs path mode" "$(printf '%s' "$OUT" | jqv "'$SCRIPTS/reports.py' in d['data']['commands'][0]['command']")" "True"

OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target nanobot --at-time 21:45)"
check "nanobot cron expr" "$(printf '%s' "$OUT" | jqv "d['data']['cron_expr']")" "45 21 * * *"
check "nanobot invocation" "$(printf '%s' "$OUT" | jqv "'\$journal' in d['data']['message']")" "True"
OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target hermes)"
check "hermes skills" "$(printf '%s' "$OUT" | jqv "d['data']['skills'][0]")" "journal"
check "hermes script" "$(printf '%s' "$OUT" | jqv "'reports.py' in d['data']['script']")" "True"

# uniform scheduler contract
OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target nanobot)"
check "journal store key" "$(printf '%s' "$OUT" | jqv "'store' in d['data']")" "True"
check "journal name key" "$(printf '%s' "$OUT" | jqv "d['data']['name']")" "journal-weekly"
check "journal step report" "$(printf '%s' "$OUT" | jqv "d['data']['commands'][0]['step']")" "report"
check "journal add action" "$(printf '%s' "$OUT" | jqv "d['data']['action']")" "add"

OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target nanobot --action disable --job journal-weekly)"
check "journal disable action" "$(printf '%s' "$OUT" | jqv "d['data']['action']")" "disable"
check "journal disable installs nothing" "$(printf '%s' "$OUT" | jqv "d['data']['installs_nothing']")" "True"
check "journal disable route" "$(printf '%s' "$OUT" | jqv "any(r['via']=='webui_automations' for r in d['data']['routes'])")" "True"
expect_fail "journal action needs job" "invalid_input" run "$SCRIPTS/reports.py" schedule-hint --target nanobot --action disable

OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target crontab)"
printf '%s' "$OUT" | "$PY" -c 'import json,sys
d=json.load(sys.stdin)
open("'"$TMPDIR_SMOKE"'/cron.txt","w").write("\n".join(d["data"]["install"]["lines"])+"\n")'
sh -n "$TMPDIR_SMOKE/cron.txt" 2>/dev/null && pass || fail "crontab line not shell-parseable"
CRON_LINES="$(cat "$TMPDIR_SMOKE/cron.txt")"
case "$CRON_LINES" in *"reports.py week"*) pass;; *) fail "crontab missing week";; esac
case "$CRON_LINES" in *"* * 0 "*) pass;; *) fail "crontab not scheduled on Sunday";; esac

OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target systemd)"
check "systemd service file" "$(printf '%s' "$OUT" | jqv "'journal-weekly.service' in d['data']['install']['files']")" "True"
check "systemd timer" "$(printf '%s' "$OUT" | jqv "'OnCalendar' in d['data']['install']['files']['journal-weekly.timer']")" "True"

OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target launchd)"
printf '%s' "$OUT" | "$PY" -c 'import json,sys,plistlib
d=json.load(sys.stdin)
plistlib.loads(d["data"]["install"]["files"]["com.journal.weekly.plist"].encode())' && pass || fail "launchd plist not valid"

# Execute the emitted read-only command twice; both runs must succeed and the
# database must be unchanged.
GEN="$(run "$SCRIPTS/reports.py" schedule-hint --target generic --path-mode abs)"
RUNCMD="$(printf '%s' "$GEN" | jqv "d['data']['commands'][0]['command']")"
BEFORE="$(run "$SCRIPTS/reports.py" stats --from 2026-01-01 --to 2026-01-07)"
eval "$RUNCMD" >/dev/null 2>&1 && pass || fail "emitted report command failed"
eval "$RUNCMD" >/dev/null 2>&1 && pass || fail "emitted report command failed on second call"
AFTER="$(run "$SCRIPTS/reports.py" stats --from 2026-01-01 --to 2026-01-07)"
check "emitted command is read-only" "$AFTER" "$BEFORE"

# ===========================================================================
section "portability"
# frontmatter legitimately carries metadata.hermes; the prose must not name hosts
SKILL_BODY="$TMPDIR_SMOKE/skill_body.md"
"$PY" -c 'import sys
parts=open(sys.argv[1], encoding="utf-8").read().split("---", 2)
open(sys.argv[2], "w", encoding="utf-8").write(parts[2] if len(parts) > 2 else "")' \
  "$SKILL/SKILL.md" "$SKILL_BODY"
LEAKS="$(grep -RIl -e 'nanobot' -e 'hermes' -e 'claude' -e 'codex' -e 'kilo' -e '\$journal' \
  "$SKILL_BODY" "$SKILL/references" "$SKILL/scripts" \
  | grep -v -e "$SKILL/references/scheduling.md" -e "$SKILL/scripts/reports.py" || true)"
if [ -z "$LEAKS" ]; then pass; else fail "host tokens leaked into: $LEAKS"; fi
grep -q 'TODO' "$SKILL/SKILL.md" && fail "SKILL.md contains TODO" || pass
STRAY="$(find "$SKILL" -maxdepth 1 -mindepth 1 ! -name SKILL.md ! -name scripts ! -name references ! -name assets ! -name README.md ! -name LICENSE ! -name .gitignore ! -name tests)"
[ -z "$STRAY" ] && pass || fail "stray files in skill root: $STRAY"
[ -x "$SCRIPTS/_lib.py" ] && fail "_lib.py should not be executable" || pass
for script in init settings entries reports; do
  [ -x "$SCRIPTS/$script.py" ] && pass || fail "$script.py is not executable"
done

# ===========================================================================
printf '\n========================================\n'
printf 'passed: %d   failed: %d\n' "$PASS" "$FAIL"
if [ "$FAIL" -ne 0 ]; then exit 1; fi
echo "smoke test OK"
