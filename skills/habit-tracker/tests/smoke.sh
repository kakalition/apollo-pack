#!/usr/bin/env bash
# End-to-end smoke test for the habit-tracker skill.
#
# Runs every script and verb against throwaway databases and checks output,
# hand-computed streaks and adherence, weekly quota edges under Monday and
# Sunday week starts, interval due dates, scheduling artifacts (including
# executing them twice), output formats, and error handling. No network
# access; bash + python3 stdlib only.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILL="$ROOT"
SCRIPTS="$SKILL/scripts"
PY="${PY:-python3}"

PASS=0
FAIL=0
TMPDIR_SMOKE="$(mktemp -d "${TMPDIR:-/tmp}/ht-smoke.XXXXXX")"
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

unset HABIT_TRACKER_DB HABIT_TRACKER_TZ HABIT_TRACKER_WEEK_START HABIT_TRACKER_DEFAULT_VIEW 2>/dev/null || true

# ===========================================================================
section "init / settings"
export HABIT_TRACKER_DB="$TMPDIR_SMOKE/main.db"
OUT="$(run "$SCRIPTS/init.py" init)"
check "init ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
check "init first run" "$(printf '%s' "$OUT" | jqv "d['data']['already_initialized']")" "False"
check "init schema version" "$(printf '%s' "$OUT" | jqv "d['data']['schema_version']")" "1"
OUT="$(run "$SCRIPTS/init.py" init)"
check "init idempotent" "$(printf '%s' "$OUT" | jqv "d['data']['already_initialized']")" "True"

OUT="$(run "$SCRIPTS/settings.py" show)"
check "settings default tz" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['tz']")" "UTC"
check "settings default week start" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['week_start']")" "mon"
check "settings initialized" "$(printf '%s' "$OUT" | jqv "d['data']['initialized']")" "True"

OUT="$(run "$SCRIPTS/settings.py" set --tz Asia/Jakarta --week-start sun)"
check "settings set tz" "$(printf '%s' "$OUT" | jqv "d['data']['changed']['tz']")" "Asia/Jakarta"
check "settings set week start" "$(printf '%s' "$OUT" | jqv "d['data']['stored']['week_start']")" "sun"
OUT="$(run "$SCRIPTS/settings.py" get --key tz)"
check "settings get key" "$(printf '%s' "$OUT" | jqv "d['data']['value']")" "Asia/Jakarta"
OUT="$(env HABIT_TRACKER_TZ=Europe/Paris "$PY" "$SCRIPTS/settings.py" show)"
check "settings env override" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['tz']")" "Europe/Paris"
expect_fail "settings unknown key" "not_found" run "$SCRIPTS/settings.py" get --key nope
expect_usage "settings bad week start" run "$SCRIPTS/settings.py" set --week-start weird
expect_fail "settings set no flags" "invalid_input" run "$SCRIPTS/settings.py" set
# put week start back to Monday for the rest of the main db checks
run "$SCRIPTS/settings.py" set --week-start mon >/dev/null

# ===========================================================================
section "habits CRUD"
run "$SCRIPTS/habits.py" add --name Read --cadence daily --start 2026-01-01 >/dev/null
OUT="$(run "$SCRIPTS/habits.py" add --name Run --cadence weekly --count 3 --start 2026-01-05)"
check "weekly cadence count" "$(printf '%s' "$OUT" | jqv "d['data']['cadence_count']")" "3"
run "$SCRIPTS/habits.py" add --name Tidy --cadence interval --count 2 --start 2026-01-01 >/dev/null
expect_fail "daily rejects count" "invalid_cadence" run "$SCRIPTS/habits.py" add --name Bad --cadence daily --count 2 --start 2026-01-01
expect_fail "duplicate habit" "conflict" run "$SCRIPTS/habits.py" add --name Read --cadence daily --start 2026-01-01

OUT="$(run "$SCRIPTS/habits.py" list)"
check "habit list count" "$(printf '%s' "$OUT" | jqv "len(d['data'])")" "3"
OUT="$(run "$SCRIPTS/habits.py" rename Tidy --name Tidy2)"
check "habit rename" "$(printf '%s' "$OUT" | jqv "d['data']['name']")" "Tidy2"
expect_fail "rename conflict" "conflict" run "$SCRIPTS/habits.py" rename Tidy2 --name Run

OUT="$(run "$SCRIPTS/habits.py" pause Tidy2)"
check "pause hides" "$(printf '%s' "$OUT" | jqv "d['data']['active']")" "False"
check "paused list count" "$(run "$SCRIPTS/habits.py" list | jqv "len(d['data'])")" "2"
check "include inactive" "$(run "$SCRIPTS/habits.py" list --include-inactive | jqv "len(d['data'])")" "3"
OUT="$(run "$SCRIPTS/habits.py" resume Tidy2)"
check "resume active" "$(printf '%s' "$OUT" | jqv "d['data']['active']")" "True"
OUT="$(run "$SCRIPTS/habits.py" archive Tidy2)"
check "archive active" "$(printf '%s' "$OUT" | jqv "d['data']['active']")" "False"

OUT="$(run "$SCRIPTS/habits.py" show Run)"
check "show run stats" "$(printf '%s' "$OUT" | jqv "'counts' in d['data']['stats']")" "True"
OUT="$(run "$SCRIPTS/habits.py" edit Run --count 4)"
check "edit count" "$(printf '%s' "$OUT" | jqv "d['data']['cadence_count']")" "4"
expect_fail "edit with no fields" "invalid_input" run "$SCRIPTS/habits.py" edit Run
expect_fail "delete unknown" "not_found" run "$SCRIPTS/habits.py" delete Nope

run "$SCRIPTS/habits.py" add --name Temp --cadence daily --start 2026-01-01 >/dev/null
expect_fail "delete needs confirm" "invalid_input" run "$SCRIPTS/habits.py" delete Temp
OUT="$(run "$SCRIPTS/habits.py" delete Temp --yes)"
check "delete cascades" "$(printf '%s' "$OUT" | jqv "d['data']['deleted']")" "True"
expect_usage "unknown verb" run "$SCRIPTS/habits.py" bogus
expect_usage "missing required flag" run "$SCRIPTS/habits.py" add --cadence daily

# ===========================================================================
section "daily cadence"
run "$SCRIPTS/habits.py" add --name Med --cadence daily --start 2026-01-01 >/dev/null
run "$SCRIPTS/checkins.py" done Med --date 2026-01-01 >/dev/null
run "$SCRIPTS/checkins.py" done Med --date 2026-01-02 >/dev/null
run "$SCRIPTS/checkins.py" skip Med --date 2026-01-03 >/dev/null
run "$SCRIPTS/checkins.py" done Med --date 2026-01-04 >/dev/null
run "$SCRIPTS/checkins.py" fail Med --date 2026-01-05 >/dev/null
run "$SCRIPTS/checkins.py" done Med --date 2026-01-06 >/dev/null

OUT="$(run "$SCRIPTS/reports.py" streaks --habit Med --as-of 2026-01-06)"
# done on 1,2,4,6 (4); skip on 3; fail on 5 -> streak breaks at 5, longest 3
check "daily done count" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['done']")" "4"
check "daily skip count" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['skip']")" "1"
check "daily fail count" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['fail']")" "1"
check "daily miss count" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['miss']")" "0"
check "daily current streak" "$(printf '%s' "$OUT" | jqv "d['data'][0]['current_streak']")" "1"
check "daily longest streak" "$(printf '%s' "$OUT" | jqv "d['data'][0]['longest_streak']")" "3"
check "daily adherence" "$(printf '%s' "$OUT" | jqv "d['data'][0]['adherence_pct'] == 80.0")" "True"
check "daily last done" "$(printf '%s' "$OUT" | jqv "d['data'][0]['last_done']")" "2026-01-06"

OUT="$(run "$SCRIPTS/reports.py" streaks --habit Med --as-of 2026-01-07)"
check "today pending is not a break" "$(printf '%s' "$OUT" | jqv "d['data'][0]['pending']")" "True"
check "pending keeps streak" "$(printf '%s' "$OUT" | jqv "d['data'][0]['current_streak']")" "1"
OUT="$(run "$SCRIPTS/reports.py" streaks --habit Med --as-of 2026-01-08)"
check "past miss counts" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['miss']")" "1"
check "past miss breaks streak" "$(printf '%s' "$OUT" | jqv "d['data'][0]['current_streak']")" "0"

# adherence over 2026-01-01..07 (as-of is real today, so the 7th is a miss):
# done 4, skip 1, fail 1, miss 1 -> 4 / (4+1+1) = 66.7, skips excluded
OUT="$(run "$SCRIPTS/reports.py" adherence --from 2026-01-01 --to 2026-01-07 --habit Med)"
check "adherence done" "$(printf '%s' "$OUT" | jqv "d['data']['habits'][0]['counts']['done']")" "4"
check "adherence skip" "$(printf '%s' "$OUT" | jqv "d['data']['habits'][0]['counts']['skip']")" "1"
check "adherence fail" "$(printf '%s' "$OUT" | jqv "d['data']['habits'][0]['counts']['fail']")" "1"
check "adherence miss" "$(printf '%s' "$OUT" | jqv "d['data']['habits'][0]['counts']['miss']")" "1"
check "adherence pct" "$(printf '%s' "$OUT" | jqv "d['data']['habits'][0]['adherence_pct'] == 66.7")" "True"

OUT="$(run "$SCRIPTS/reports.py" history --habit Med)"
check "history rows" "$(printf '%s' "$OUT" | jqv "len(d['data'])")" "6"
OUT="$(run "$SCRIPTS/checkins.py" list --habit Med)"
check "checkin list" "$(printf '%s' "$OUT" | jqv "len(d['data'])")" "6"
OUT="$(run "$SCRIPTS/checkins.py" list --habit Med --status done)"
check "checkin status filter" "$(printf '%s' "$OUT" | jqv "len(d['data'])")" "4"
OUT="$(run "$SCRIPTS/checkins.py" list --habit Med --from 2026-01-04 --to 2026-01-05)"
check "checkin date filter" "$(printf '%s' "$OUT" | jqv "len(d['data'])")" "2"

expect_fail "duplicate checkin" "conflict" run "$SCRIPTS/checkins.py" done Med --date 2026-01-06
OUT="$(run "$SCRIPTS/checkins.py" undo Med --date 2026-01-06)"
check "undo removes" "$(printf '%s' "$OUT" | jqv "d['data']['removed']")" "1"
check "undo shrinks list" "$(run "$SCRIPTS/checkins.py" list --habit Med | jqv "len(d['data'])")" "5"
run "$SCRIPTS/checkins.py" done Med --date 2026-01-06 >/dev/null
expect_fail "undo unknown" "not_found" run "$SCRIPTS/checkins.py" undo Med --date 2026-02-01
expect_fail "unknown habit" "not_found" run "$SCRIPTS/checkins.py" done Nope --date 2026-01-01
expect_fail "bad date" "invalid_date" run "$SCRIPTS/checkins.py" done Med --date 2026-13-01

# ===========================================================================
section "weekly cadence (Monday start)"
export HABIT_TRACKER_DB="$TMPDIR_SMOKE/weekly.db"
run "$SCRIPTS/init.py" init >/dev/null
run "$SCRIPTS/habits.py" add --name Gym --cadence weekly --count 2 --start 2026-01-05 >/dev/null
run "$SCRIPTS/checkins.py" done Gym --date 2026-01-05 >/dev/null
run "$SCRIPTS/checkins.py" done Gym --date 2026-01-06 >/dev/null
run "$SCRIPTS/checkins.py" done Gym --date 2026-01-12 >/dev/null
run "$SCRIPTS/checkins.py" skip Gym --date 2026-01-13 >/dev/null

# week 1 (05-11) satisfied with 2; week 2 (12-18) has a skip -> excused
OUT="$(run "$SCRIPTS/reports.py" streaks --habit Gym --as-of 2026-01-18)"
check "weekly satisfied week" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['done']")" "1"
check "weekly excused week" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['skip']")" "1"
check "weekly excused misses" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['miss']")" "0"
check "weekly excused streak" "$(printf '%s' "$OUT" | jqv "d['data'][0]['current_streak']")" "1"
check "weekly current week start" "$(printf '%s' "$OUT" | jqv "d['data'][0]['current_week']['start']")" "2026-01-12"
check "weekly adherence" "$(printf '%s' "$OUT" | jqv "d['data'][0]['adherence_pct'] == 100.0")" "True"

# week 3 (19-25) has neither done-quota nor skip -> miss; current streak resets
OUT="$(run "$SCRIPTS/reports.py" streaks --habit Gym --as-of 2026-01-26)"
check "weekly missed week" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['miss']")" "1"
check "weekly miss resets" "$(printf '%s' "$OUT" | jqv "d['data'][0]['current_streak']")" "0"
check "weekly miss adherence" "$(printf '%s' "$OUT" | jqv "d['data'][0]['adherence_pct'] == 50.0")" "True"

# ===========================================================================
section "weekly cadence (Sunday start boundary)"
export HABIT_TRACKER_DB="$TMPDIR_SMOKE/weekly2.db"
run "$SCRIPTS/init.py" init >/dev/null
run "$SCRIPTS/habits.py" add --name Gym2 --cadence weekly --count 2 --start 2026-01-11 >/dev/null
run "$SCRIPTS/checkins.py" done Gym2 --date 2026-01-11 >/dev/null   # Sunday
run "$SCRIPTS/checkins.py" done Gym2 --date 2026-01-12 >/dev/null   # Monday

OUT="$(env HABIT_TRACKER_WEEK_START=sun "$PY" "$SCRIPTS/reports.py" streaks --habit Gym2 --as-of 2026-01-17)"
check "sun start groups both" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['done']")" "1"
check "sun start satisfied" "$(printf '%s' "$OUT" | jqv "d['data'][0]['current_streak']")" "1"
check "sun start no miss" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['miss']")" "0"

OUT="$(env HABIT_TRACKER_WEEK_START=mon "$PY" "$SCRIPTS/reports.py" streaks --habit Gym2 --as-of 2026-01-17)"
check "mon start splits weeks" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['miss']")" "1"
check "mon start pending" "$(printf '%s' "$OUT" | jqv "d['data'][0]['pending']")" "True"
check "mon start broken" "$(printf '%s' "$OUT" | jqv "d['data'][0]['current_streak']")" "0"

# ===========================================================================
section "interval cadence"
export HABIT_TRACKER_DB="$TMPDIR_SMOKE/interval.db"
run "$SCRIPTS/init.py" init >/dev/null
run "$SCRIPTS/habits.py" add --name Stretch --cadence interval --count 3 --start 2026-01-01 >/dev/null
run "$SCRIPTS/checkins.py" done Stretch --date 2026-01-01 >/dev/null
run "$SCRIPTS/checkins.py" done Stretch --date 2026-01-04 >/dev/null

# due 01, 04 done; 07 overdue -> miss; 10 pending
OUT="$(run "$SCRIPTS/reports.py" streaks --habit Stretch --as-of 2026-01-10)"
check "interval done" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['done']")" "2"
check "interval overdue miss" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['miss']")" "1"
check "interval longest" "$(printf '%s' "$OUT" | jqv "d['data'][0]['longest_streak']")" "2"
check "interval pending" "$(printf '%s' "$OUT" | jqv "d['data'][0]['pending']")" "True"
check "interval next due" "$(printf '%s' "$OUT" | jqv "d['data'][0]['next_due']")" "2026-01-13"
check "interval adherence" "$(printf '%s' "$OUT" | jqv "d['data'][0]['adherence_pct'] == 66.7")" "True"

# an on-time done on the next due date extends the streak: 3 done, 2 miss
run "$SCRIPTS/checkins.py" done Stretch --date 2026-01-13 >/dev/null
OUT="$(run "$SCRIPTS/reports.py" streaks --habit Stretch --as-of 2026-01-13)"
check "on-time done extends" "$(printf '%s' "$OUT" | jqv "d['data'][0]['current_streak']")" "1"
check "interval misses" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['miss']")" "2"
check "interval on-time adherence" "$(printf '%s' "$OUT" | jqv "d['data'][0]['adherence_pct'] == 60.0")" "True"

run "$SCRIPTS/habits.py" add --name Water --cadence interval --count 2 --start 2026-02-01 >/dev/null
run "$SCRIPTS/checkins.py" skip Water --date 2026-02-01 >/dev/null
OUT="$(run "$SCRIPTS/reports.py" streaks --habit Water --as-of 2026-02-03)"
check "interval skip neutral" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['skip']")" "1"
check "interval skip misses" "$(printf '%s' "$OUT" | jqv "d['data'][0]['counts']['miss']")" "0"
check "interval skip next due" "$(printf '%s' "$OUT" | jqv "d['data'][0]['next_due']")" "2026-02-05"

# ===========================================================================
section "reports, formats, and stats"
export HABIT_TRACKER_DB="$TMPDIR_SMOKE/main.db"
OUT="$(run "$SCRIPTS/reports.py" today --as-of 2026-01-06)"
check "today read only" "$(printf '%s' "$OUT" | jqv "d['data']['read_only']")" "True"
# Read (daily, unlogged) and Run (weekly, not yet satisfied) are due; Med is done
check "today due count" "$(printf '%s' "$OUT" | jqv "d['data']['due_count']")" "2"
OUT="$(run "$SCRIPTS/reports.py" due --as-of 2026-01-06 --within 0)"
check "due read only" "$(printf '%s' "$OUT" | jqv "d['data']['read_only']")" "True"
check "due count" "$(printf '%s' "$OUT" | jqv "d['data']['count']")" "2"
OUT="$(run "$SCRIPTS/reports.py" stats)"
check "stats habits" "$(printf '%s' "$OUT" | jqv "d['data']['habits']")" "4"
check "stats active" "$(printf '%s' "$OUT" | jqv "d['data']['active_habits']")" "3"
check "stats done count" "$(printf '%s' "$OUT" | jqv "d['data']['by_status']['done']")" "4"
check "stats checkins" "$(printf '%s' "$OUT" | jqv "d['data']['checkins']")" "6"
OUT="$(run "$SCRIPTS/reports.py" streaks --habit Read)"
check "streaks default as-of" "$(printf '%s' "$OUT" | jqv "'as_of' in d['data'][0]")" "True"

OUT="$(run "$SCRIPTS/habits.py" list --format table)"
case "$OUT" in *"name"*) pass;; *) fail "table output missing header";; esac
case "$OUT" in *'{'*) fail "table output should not be JSON";; *) pass;; esac
QUIET="$(run "$SCRIPTS/reports.py" stats --quiet)"
check "quiet suppresses output" "$QUIET" ""

# missing/bad arguments
expect_usage "reports unknown verb" run "$SCRIPTS/reports.py" bogus
expect_fail "adherence bad range" "invalid_input" run "$SCRIPTS/reports.py" adherence --from 2026-02-01 --to 2026-01-01

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
check "nanobot invocation" "$(printf '%s' "$OUT" | jqv "'\$habit-tracker' in d['data']['message']")" "True"
check "nanobot cron tool" "$(printf '%s' "$OUT" | jqv "d['data']['cron_tool']['action']")" "add"
OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target hermes)"
check "hermes skills" "$(printf '%s' "$OUT" | jqv "d['data']['skills'][0]")" "habit-tracker"
check "hermes script" "$(printf '%s' "$OUT" | jqv "'reports.py' in d['data']['script']")" "True"

# uniform scheduler contract
OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target nanobot)"
check "habit store key" "$(printf '%s' "$OUT" | jqv "'store' in d['data']")" "True"
check "habit name key" "$(printf '%s' "$OUT" | jqv "d['data']['name']")" "habit-tracker-daily"
check "habit step report" "$(printf '%s' "$OUT" | jqv "d['data']['commands'][0]['step']")" "report"
check "habit add action" "$(printf '%s' "$OUT" | jqv "d['data']['action']")" "add"

OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target nanobot --action disable --job habit-tracker-daily)"
check "habit disable action" "$(printf '%s' "$OUT" | jqv "d['data']['action']")" "disable"
check "habit disable installs nothing" "$(printf '%s' "$OUT" | jqv "d['data']['installs_nothing']")" "True"
check "habit disable route" "$(printf '%s' "$OUT" | jqv "any(r['via']=='webui_automations' for r in d['data']['routes'])")" "True"
OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target systemd --action disable --job habit-tracker-daily)"
check "habit systemd manage" "$(printf '%s' "$OUT" | jqv "d['data']['routes'][0]['via']")" "systemd"
expect_fail "habit action needs job" "invalid_input" run "$SCRIPTS/reports.py" schedule-hint --target nanobot --action disable

OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target crontab)"
printf '%s' "$OUT" | "$PY" -c 'import json,sys
d=json.load(sys.stdin)
open("'"$TMPDIR_SMOKE"'/cron.txt","w").write("\n".join(d["data"]["install"]["lines"])+"\n")'
sh -n "$TMPDIR_SMOKE/cron.txt" 2>/dev/null && pass || fail "crontab line not shell-parseable"
CRON_LINES="$(cat "$TMPDIR_SMOKE/cron.txt")"
case "$CRON_LINES" in *"reports.py due"*) pass;; *) fail "crontab missing due";; esac
case "$CRON_LINES" in *'\%F'*) pass;; *) fail "crontab percent not escaped";; esac

OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target systemd)"
check "systemd service file" "$(printf '%s' "$OUT" | jqv "'habit-tracker-due.service' in d['data']['install']['files']")" "True"
check "systemd escaped percent" "$(printf '%s' "$OUT" | jqv "'%%F' in d['data']['install']['files']['habit-tracker-due.service']")" "True"
check "systemd timer" "$(printf '%s' "$OUT" | jqv "'OnCalendar' in d['data']['install']['files']['habit-tracker-due.timer']")" "True"

OUT="$(run "$SCRIPTS/reports.py" schedule-hint --target launchd)"
printf '%s' "$OUT" | "$PY" -c 'import json,sys,plistlib
d=json.load(sys.stdin)
plistlib.loads(d["data"]["install"]["files"]["com.habit-tracker.due.plist"].encode())' && pass || fail "launchd plist not valid"

# Execute the emitted read-only command twice; both runs must succeed and
# leave the database unchanged.
GEN="$(run "$SCRIPTS/reports.py" schedule-hint --target generic --path-mode abs)"
RUNCMD="$(printf '%s' "$GEN" | jqv "d['data']['commands'][0]['command']")"
BEFORE="$(run "$SCRIPTS/reports.py" stats)"
eval "$RUNCMD" >/dev/null 2>&1 && pass || fail "emitted report command failed"
eval "$RUNCMD" >/dev/null 2>&1 && pass || fail "emitted report command failed on second call"
AFTER="$(run "$SCRIPTS/reports.py" stats)"
check "emitted command is read-only" "$AFTER" "$BEFORE"

# ===========================================================================
section "portability"
# frontmatter legitimately carries metadata.hermes; the prose must not name hosts
SKILL_BODY="$TMPDIR_SMOKE/skill_body.md"
"$PY" -c 'import sys
parts=open(sys.argv[1], encoding="utf-8").read().split("---", 2)
open(sys.argv[2], "w", encoding="utf-8").write(parts[2] if len(parts) > 2 else "")' \
  "$SKILL/SKILL.md" "$SKILL_BODY"
LEAKS="$(grep -RIl -e 'nanobot' -e 'hermes' -e 'claude' -e 'codex' -e 'kilo' -e '\$habit-tracker' \
  "$SKILL_BODY" "$SKILL/references" "$SKILL/scripts" \
  | grep -v -e "$SKILL/references/scheduling.md" -e "$SKILL/scripts/reports.py" || true)"
if [ -z "$LEAKS" ]; then pass; else fail "host tokens leaked into: $LEAKS"; fi
grep -q 'TODO' "$SKILL/SKILL.md" && fail "SKILL.md contains TODO" || pass
STRAY="$(find "$SKILL" -maxdepth 1 -mindepth 1 ! -name SKILL.md ! -name scripts ! -name references ! -name assets ! -name README.md ! -name LICENSE ! -name .gitignore ! -name tests)"
[ -z "$STRAY" ] && pass || fail "stray files in skill root: $STRAY"
[ -x "$SCRIPTS/_lib.py" ] && fail "_lib.py should not be executable" || pass
for script in init settings habits checkins reports; do
  [ -x "$SCRIPTS/$script.py" ] && pass || fail "$script.py is not executable"
done

# ===========================================================================
printf '\n========================================\n'
printf 'passed: %d   failed: %d\n' "$PASS" "$FAIL"
if [ "$FAIL" -ne 0 ]; then exit 1; fi
echo "smoke test OK"
