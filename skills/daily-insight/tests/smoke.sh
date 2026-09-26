#!/usr/bin/env bash
# Tier 1: hermetic end-to-end smoke test for the daily-insight skill.
#
# Runs every script and verb against throwaway data roots using the offline
# `hash` embedder. No network access: bash + python3 + the optional pip
# dependencies (chromadb, pypdf, python-docx) only.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILL="$ROOT"
SCRIPTS="$SKILL/scripts"
FIXTURES="$ROOT/tests/fixtures"
PY="${PY:-python3}"
export PYTHONWARNINGS="ignore"

PASS=0
FAIL=0
TMPDIR_SMOKE="$(mktemp -d "${TMPDIR:-/tmp}/di-smoke.XXXXXX")"
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

expect_usage() { # expect_usage DESC CMD...
  local desc="$1"; shift
  "$@" >/dev/null 2>&1; local rc=$?
  if [ "$rc" -eq 2 ]; then pass; else fail "$desc: expected exit 2, got $rc"; fi
}

have_deps() {
  "$PY" -c 'import chromadb, pypdf, docx' >/dev/null 2>&1
}

if ! have_deps; then
  printf 'SKIP: tier 1 needs chromadb, pypdf, and python-docx (pip install -r requirements.txt)\n'
  exit 0
fi

unset DAILY_INSIGHT_HOME 2>/dev/null || true

# ===========================================================================
section "init / settings"
export DAILY_INSIGHT_HOME="$TMPDIR_SMOKE/main"
OUT="$(run "$SCRIPTS/init.py" init)"
check "init ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
check "init schema" "$(printf '%s' "$OUT" | jqv "d['data']['schema_version']")" "1"
check "init chromadb present" "$(printf '%s' "$OUT" | jqv "d['data']['dependencies']['chromadb']")" "True"

OUT="$(run "$SCRIPTS/init.py" init)"
check "init idempotent" "$(printf '%s' "$OUT" | jqv "d['data']['already_initialized']")" "True"

OUT="$(run "$SCRIPTS/settings.py" show)"
check "settings budget default" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['budget']")" "5"
check "settings wake default" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['wake']")" "08:00-22:00"
check "settings hash default" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['embed_mode']")" "hash"

OUT="$(run "$SCRIPTS/settings.py" set --budget 3 --wake 09:00-18:00 --strategy coverage --tz Asia/Jakarta)"
check "settings set budget" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['budget']")" "3"
check "settings set wake" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['wake']")" "09:00-18:00"
check "settings set tz" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['tz']")" "Asia/Jakarta"

OUT="$(run "$SCRIPTS/settings.py" get --key budget)"
check "settings get key" "$(printf '%s' "$OUT" | jqv "d['data']['value']")" "3"
OUT="$(run "$SCRIPTS/settings.py" get)"
check "settings get all" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['wake']")" "09:00-18:00"
expect_fail "settings get unknown" "not_found" run "$SCRIPTS/settings.py" get --key nope
expect_fail "settings set empty" "usage" run "$SCRIPTS/settings.py" set

# secrets are never echoed: only the env-var name is stored
export DAILY_INSIGHT_EMBED_API_KEY="sk-should-never-leak-123"
run "$SCRIPTS/settings.py" set --embed-api-key-env DAILY_INSIGHT_EMBED_API_KEY >/dev/null
OUT="$(run "$SCRIPTS/settings.py" show)"
case "$OUT" in
  *"sk-should-never-leak-123"*) fail "API key leaked into settings output" ;;
  *) pass ;;
esac
check "settings stores env name" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['embed_api_key_env']")" "DAILY_INSIGHT_EMBED_API_KEY"

# ===========================================================================
section "materials"
run "$SCRIPTS/materials.py" add --name "Book A" --cadence-count 2 --cadence-period day >/dev/null
run "$SCRIPTS/materials.py" add --name "Book B" --cadence-count 1 --cadence-period day >/dev/null
OUT="$(run "$SCRIPTS/materials.py" list)"
check "materials list" "$(printf '%s' "$OUT" | jqv "len(d['data'])")" "2"
check "materials cadence" "$(printf '%s' "$OUT" | jqv "[m for m in d['data'] if m['name']=='Book A'][0]['cadence']")" "2/day"

OUT="$(run "$SCRIPTS/materials.py" cadence "Book B" --count 1 --period week)"
check "cadence weekly weekdays" "$(printf '%s' "$OUT" | jqv "len(d['data']['weekdays'])")" "1"
run "$SCRIPTS/materials.py" cadence "Book B" --count 1 --period day >/dev/null

OUT="$(run "$SCRIPTS/materials.py" priority "Book A" --value 10)"
check "priority set" "$(printf '%s' "$OUT" | jqv "d['data']['priority']")" "10"
run "$SCRIPTS/materials.py" priority "Book A" --value 100 >/dev/null

run "$SCRIPTS/materials.py" rename "Book B" --name "Book Beta" >/dev/null
OUT="$(run "$SCRIPTS/materials.py" list)"
check "rename" "$(printf '%s' "$OUT" | jqv "'Book Beta' in [m['name'] for m in d['data']]")" "True"
run "$SCRIPTS/materials.py" rename "Book Beta" --name "Book B" >/dev/null

run "$SCRIPTS/materials.py" archive "Book B" >/dev/null
OUT="$(run "$SCRIPTS/materials.py" list)"
check "archive hidden" "$(printf '%s' "$OUT" | jqv "'Book B' in [m['name'] for m in d['data']]")" "False"
run "$SCRIPTS/materials.py" archive "Book B" --unarchive >/dev/null
OUT="$(run "$SCRIPTS/materials.py" list)"
check "unarchive shown" "$(printf '%s' "$OUT" | jqv "'Book B' in [m['name'] for m in d['data']]")" "True"

expect_fail "duplicate material" "conflict" run "$SCRIPTS/materials.py" add --name "Book A"
expect_fail "unknown material" "not_found" run "$SCRIPTS/materials.py" show Nope
expect_fail "bad cadence" "invalid_input" run "$SCRIPTS/materials.py" cadence "Book A" --count 0 --period day
expect_usage "materials add needs name" run "$SCRIPTS/materials.py" add

# ===========================================================================
section "day plan (cadence, interleave, budget)"
MON="2026-09-28"   # a Monday
OUT="$(run "$SCRIPTS/insights.py" due --date "$MON")"
check "plan slot count" "$(printf '%s' "$OUT" | jqv "len(d['data']['slots'])")" "3"
check "plan interleaved A,B,A" "$(printf '%s' "$OUT" | jqv "[s['material'] for s in d['data']['slots']]")" "['Book A', 'Book B', 'Book A']"
check "plan planned_total" "$(printf '%s' "$OUT" | jqv "d['data']['planned_total']")" "3"

# weekly material only appears on its chosen weekdays
run "$SCRIPTS/materials.py" add --name "Weekly C" --cadence-count 3 --cadence-period week >/dev/null
WDJSON="$(run "$SCRIPTS/materials.py" show "Weekly C")"
DUE_DAY="$(printf '%s' "$WDJSON" | "$PY" -c 'import json,sys,datetime
d=json.load(sys.stdin)["data"]; wd=set(d["weekdays"]); base=datetime.date(2026,9,28)
print(next((base+datetime.timedelta(days=i)).isoformat() for i in range(7) if (base+datetime.timedelta(days=i)).weekday() in wd))')"
NODUE_DAY="$(printf '%s' "$WDJSON" | "$PY" -c 'import json,sys,datetime
d=json.load(sys.stdin)["data"]; wd=set(d["weekdays"]); base=datetime.date(2026,9,28)
print(next((base+datetime.timedelta(days=i)).isoformat() for i in range(7) if (base+datetime.timedelta(days=i)).weekday() not in wd))')"
OUT="$(run "$SCRIPTS/insights.py" due --date "$DUE_DAY")"
check "weekly material due on chosen day" "$(printf '%s' "$OUT" | jqv "'Weekly C' in [s['material'] for s in d['data']['slots']]")" "True"
OUT="$(run "$SCRIPTS/insights.py" due --date "$NODUE_DAY")"
check "weekly material absent other days" "$(printf '%s' "$OUT" | jqv "'Weekly C' in [s['material'] for s in d['data']['slots']]")" "False"

# budget trims the plan and reports the drop on a fresh date
run "$SCRIPTS/settings.py" set --budget 2 >/dev/null
BUDGET_DAY="2026-10-05"
OUT="$(run "$SCRIPTS/insights.py" due --date "$BUDGET_DAY")"
check "budget slot count" "$(printf '%s' "$OUT" | jqv "len(d['data']['slots'])")" "2"
check "budget planned at least 3" "$(printf '%s' "$OUT" | jqv "d['data']['planned_total'] >= 3")" "True"
check "budget dropped remainder" "$(printf '%s' "$OUT" | jqv "len(d['data']['dropped']) == d['data']['planned_total'] - 2")" "True"
run "$SCRIPTS/settings.py" set --budget 5 >/dev/null

# ===========================================================================
section "ingest"
run "$SCRIPTS/materials.py" add --name "Pasted" >/dev/null
OUT="$(run "$SCRIPTS/ingest.py" ingest \
  --text "$(printf 'Alpha beta gamma.\n\nDelta epsilon zeta.\n\nEta theta iota.\n\nKappa lambda mu.')" \
  --material "Pasted" --chunk-size 20 --chunk-overlap 0)"
check "ingest pasted added" "$(printf '%s' "$OUT" | jqv "d['data']['chunks_added'] > 0")" "True"

OUT="$(run "$SCRIPTS/ingest.py" ingest "$FIXTURES/overview.md" --material "Book A" --chunk-size 200 --chunk-overlap 40)"
MCOUNT="$(printf '%s' "$OUT" | jqv "d['data']['chunks_added']")"
check "ingest md chunks" "$(printf '%s' "$OUT" | jqv "d['data']['chunks_added'] > 3")" "True"
check "ingest marks material" "$(printf '%s' "$OUT" | jqv "d['data']['materials'][0]['chunk_count'] == $MCOUNT")" "True"

OUT="$(run "$SCRIPTS/ingest.py" ingest "$FIXTURES/overview.md" --material "Book A" --chunk-size 200 --chunk-overlap 40)"
check "ingest duplicate skipped" "$(printf '%s' "$OUT" | jqv "d['data']['chunks_added']")" "0"
check "ingest duplicate counted" "$(printf '%s' "$OUT" | jqv "d['data']['chunks_skipped'] == $MCOUNT")" "True"

OUT="$(run "$SCRIPTS/ingest.py" ingest "$FIXTURES/notes.txt" --material "Book B" --chunk-size 200)"
check "ingest second material" "$(printf '%s' "$OUT" | jqv "d['data']['chunks_added'] > 0")" "True"

OUT="$(run "$SCRIPTS/ingest.py" ingest "$FIXTURES/article.docx" --material "Doc D" --chunk-size 200)"
check "ingest docx" "$(printf '%s' "$OUT" | jqv "d['data']['chunks_added'] > 0")" "True"
OUT="$(run "$SCRIPTS/ingest.py" ingest "$FIXTURES/paper.pdf" --material "Paper E" --chunk-size 200)"
check "ingest pdf" "$(printf '%s' "$OUT" | jqv "d['data']['chunks_added'] > 0")" "True"
run "$SCRIPTS/materials.py" archive "Doc D" >/dev/null
run "$SCRIPTS/materials.py" archive "Paper E" >/dev/null

# dry run writes nothing
BEFORE="$(run "$SCRIPTS/init.py" init | jqv "d['data']['vector_count']")"
OUT="$(run "$SCRIPTS/ingest.py" ingest "$FIXTURES/notes.txt" --material "Dry F" --dry-run)"
check "ingest dry-run flag" "$(printf '%s' "$OUT" | jqv "d['data']['dry_run']")" "True"
check "ingest dry-run plans chunks" "$(printf '%s' "$OUT" | jqv "d['data']['chunks_added'] > 0")" "True"
AFTER="$(run "$SCRIPTS/init.py" init | jqv "d['data']['vector_count']")"
check "dry-run wrote nothing" "$AFTER" "$BEFORE"
expect_fail "dry-run material not created" "not_found" run "$SCRIPTS/materials.py" show "Dry F"

# replace re-ingests and keeps chunk_count stable
OUT="$(run "$SCRIPTS/ingest.py" ingest "$FIXTURES/overview.md" --material "Book A" --chunk-size 200 --chunk-overlap 40 --replace)"
check "ingest replace added" "$(printf '%s' "$OUT" | jqv "d['data']['chunks_added'] == $MCOUNT")" "True"
check "ingest replace stable" "$(printf '%s' "$OUT" | jqv "d['data']['materials'][0]['chunk_count'] == $MCOUNT")" "True"

# embedding rows match chunks in the vector store
VECTORS="$(run "$SCRIPTS/init.py" init | jqv "d['data']['vector_count']")"
CHUNKS="$(run "$SCRIPTS/reports.py" stats | jqv "d['data']['counts']['chunks']")"
check "vectors match chunks" "$VECTORS" "$CHUNKS"

expect_fail "ingest missing file" "not_found" run "$SCRIPTS/ingest.py" ingest "$TMPDIR_SMOKE/nope.md" --material "Book A"

# ===========================================================================
section "delivery (idempotency, coverage, cycling)"
export DAILY_INSIGHT_HOME="$TMPDIR_SMOKE/deliver"
run "$SCRIPTS/init.py" init >/dev/null
run "$SCRIPTS/settings.py" set --budget 5 --wake 08:00-22:00 --dedup-threshold 1.0 >/dev/null
run "$SCRIPTS/materials.py" add --name "Queue" --cadence-count 5 --cadence-period day >/dev/null
run "$SCRIPTS/ingest.py" ingest \
  --text "$(printf 'One alpha beta.\n\nTwo gamma delta.\n\nThree epsilon.\n\nFour zeta eta.\n\nFive theta iota.\n\nSix kappa mu.')" \
  --material "Queue" --chunk-size 20 --chunk-overlap 0 >/dev/null
check "queue has enough chunks" "$(run "$SCRIPTS/materials.py" show "Queue" | jqv "d['data']['chunk_count'] >= 5")" "True"

D1="2026-08-03"
ORDINALS=""
for n in 1 2 3 4 5; do
  OUT="$(run "$SCRIPTS/insights.py" next --date "$D1")"
  check "next $n delivered" "$(printf '%s' "$OUT" | jqv "d['data']['status']")" "delivered"
  ORD="$(printf '%s' "$OUT" | jqv "d['data']['chunk']['ordinal']")"
  ORDINALS="$ORDINALS $ORD"
done
DISTINCT="$(printf '%s' "$ORDINALS" | tr ' ' '\n' | grep -v '^$' | sort -u | wc -l | tr -d ' ')"
check "five distinct chunks" "$DISTINCT" "5"

OUT="$(run "$SCRIPTS/insights.py" next --date "$D1")"
check "next exhausted" "$(printf '%s' "$OUT" | jqv "d['data']['status']")" "nothing_due"
OUT="$(run "$SCRIPTS/insights.py" next --date "$D1")"
check "next rerun no-op" "$(printf '%s' "$OUT" | jqv "d['data']['status']")" "nothing_due"
check "deliveries counted once" "$(run "$SCRIPTS/reports.py" stats | jqv "d['data']['counts']['deliveries']")" "5"

# run is idempotent and catches up a whole day
D2="2026-08-04"
OUT="$(run "$SCRIPTS/insights.py" run --date "$D2" --until 23:59)"
check "run delivered day" "$(printf '%s' "$OUT" | jqv "d['data']['delivered_count']")" "5"
OUT="$(run "$SCRIPTS/insights.py" run --date "$D2" --until 23:59)"
check "run rerun idempotent" "$(printf '%s' "$OUT" | jqv "d['data']['delivered_count']")" "0"

# coverage: a 4-chunk material is fully covered before cycling
export DAILY_INSIGHT_HOME="$TMPDIR_SMOKE/coverage"
run "$SCRIPTS/init.py" init >/dev/null
run "$SCRIPTS/settings.py" set --budget 5 --dedup-threshold 1.0 >/dev/null
run "$SCRIPTS/materials.py" add --name "Small" --cadence-count 5 --cadence-period day >/dev/null
run "$SCRIPTS/ingest.py" ingest \
  --text "$(printf 'Aaa one two.\n\nBbb three four.\n\nCcc five six.\n\nDdd seven eight.')" \
  --material "Small" --chunk-size 20 --chunk-overlap 0 >/dev/null
check "small material chunks" "$(run "$SCRIPTS/materials.py" show "Small" | jqv "d['data']['chunk_count']")" "4"
D3="2026-08-05"
SEEN=""
for n in 1 2 3 4 5; do
  OUT="$(run "$SCRIPTS/insights.py" next --date "$D3")"
  SEEN="$SEEN $(printf '%s' "$OUT" | jqv "d['data']['chunk']['ordinal']")"
done
check "coverage visits all chunks first" "$(printf '%s' "$SEEN" | tr ' ' '\n' | grep -v '^$' | sort -u | wc -l | tr -d ' ')" "4"
check "exhausted material cycles oldest" "$(printf '%s' "$SEEN" | tr ' ' '\n' | grep -v '^$' | tail -n 1)" "0"
OUT="$(run "$SCRIPTS/reports.py" coverage)"
check "coverage 100%" "$(printf '%s' "$OUT" | jqv "[m for m in d['data']['materials'] if m['name']=='Small'][0]['coverage_pct']")" "100.0"
check "coverage delivered count" "$(printf '%s' "$OUT" | jqv "[m for m in d['data']['materials'] if m['name']=='Small'][0]['delivered_chunks']")" "4"
check "history respects limit" "$(run "$SCRIPTS/reports.py" history --limit 3 | jqv "d['data']['count']")" "3"

# ===========================================================================
section "errors"
export DAILY_INSIGHT_HOME="$TMPDIR_SMOKE/main"
expect_usage "bad flag" run "$SCRIPTS/insights.py" due --bogus
expect_fail "unknown date" "invalid_date" run "$SCRIPTS/insights.py" due --date 2026-13-01
expect_fail "unknown material show" "not_found" run "$SCRIPTS/materials.py" show Ghost
expect_fail "unknown setting" "not_found" run "$SCRIPTS/settings.py" get --key ghost
expect_usage "bad strategy choice" run "$SCRIPTS/settings.py" set --strategy sideways

# missing dependencies degrade with a clear, actionable error
BADDEPS="$TMPDIR_SMOKE/baddeps"
mkdir -p "$BADDEPS"
printf 'raise ImportError("chromadb blocked for the test")\n' > "$BADDEPS/chromadb.py"
MISSING="$(env PYTHONPATH="$BADDEPS" "$PY" "$SCRIPTS/init.py" init --home "$TMPDIR_SMOKE/nodeps" 2>/dev/null)"; rc=$?
check "missing dep exit" "$rc" "1"
check "missing dep code" "$(printf '%s' "$MISSING" | jqv "d['error']['code']")" "dependency_missing"
env PYTHONPATH="$BADDEPS" "$PY" "$SCRIPTS/reports.py" stats --home "$TMPDIR_SMOKE/main" >/dev/null 2>&1 \
  && pass || fail "reports.py should run without chromadb"

# ===========================================================================
section "host env overrides + providers"
export DAILY_INSIGHT_HOME="$TMPDIR_SMOKE/main"
OUT="$(env DAILY_INSIGHT_BUDGET=9 "$PY" "$SCRIPTS/settings.py" show)"
check "env override wins" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['budget']")" "9"
check "env override reported" "$(printf '%s' "$OUT" | jqv "d['data']['env_overrides'].get('budget')")" "9"
OUT="$(run "$SCRIPTS/settings.py" show)"
check "stored budget unchanged" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['budget']")" "5"

# the override reaches the planner, not just the settings view
OUT="$(env DAILY_INSIGHT_BUDGET=2 "$PY" "$SCRIPTS/insights.py" due --date 2026-10-06 --home "$TMPDIR_SMOKE/main")"
check "env budget trims plan" "$(printf '%s' "$OUT" | jqv "len(d['data']['slots'])")" "2"

# sane defaults: an OpenAI-compatible endpoint can be configured with env only,
# no settings write and no network needed to report that it is ready
OUT="$(env DAILY_INSIGHT_EMBED_MODE=remote DAILY_INSIGHT_EMBED_PROVIDER=openai \
  DAILY_INSIGHT_EMBED_BASE_URL=https://openrouter.ai/api/v1 \
  DAILY_INSIGHT_EMBED_MODEL=openai/text-embedding-3-small \
  DAILY_INSIGHT_EMBED_API_KEY=sk-test "$PY" "$SCRIPTS/settings.py" show)"
check "env-only remote configured" "$(printf '%s' "$OUT" | jqv "d['data']['embedding_configured']")" "True"
check "env-only key available" "$(printf '%s' "$OUT" | jqv "d['data']['embedding_key_available']")" "True"
check "env-only model effective" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['embed_model']")" "openai/text-embedding-3-small"

# providers: anthropic is valid for chat, rejected for embeddings before any call
run "$SCRIPTS/settings.py" set --chat-provider anthropic >/dev/null
OUT="$(run "$SCRIPTS/settings.py" show)"
check "chat provider anthropic" "$(printf '%s' "$OUT" | jqv "d['data']['settings']['chat_provider']")" "anthropic"
run "$SCRIPTS/settings.py" set --chat-provider openai >/dev/null
expect_usage "anthropic embed provider rejected" run "$SCRIPTS/settings.py" set --embed-provider anthropic
BADPROV="$(env DAILY_INSIGHT_EMBED_MODE=remote DAILY_INSIGHT_EMBED_PROVIDER=anthropic DAILY_INSIGHT_EMBED_MODEL=x \
  "$PY" "$SCRIPTS/ingest.py" ingest --text "provider guard passage" --material "Book A" \
  --home "$TMPDIR_SMOKE/main" 2>/dev/null)"; rc=$?
check "anthropic embed exit" "$rc" "1"
check "anthropic embed code" "$(printf '%s' "$BADPROV" | jqv "d['error']['code']")" "embedding_not_configured"

# ===========================================================================
section "scheduling artifacts"
export DAILY_INSIGHT_HOME="$TMPDIR_SMOKE/main"
for TARGET in generic nanobot hermes claude codex kilo crontab systemd launchd; do
  OUT="$(run "$SCRIPTS/insights.py" schedule-hint --target "$TARGET")"
  check "hint $TARGET ok" "$(printf '%s' "$OUT" | jqv "d['ok']")" "True"
  check "hint $TARGET installs nothing" "$(printf '%s' "$OUT" | jqv "d['data']['installs_nothing']")" "True"
done

OUT="$(run "$SCRIPTS/insights.py" schedule-hint --target generic --wake 09:00-18:00 --budget 3)"
check "hint slot times" "$(printf '%s' "$OUT" | jqv "len(d['data']['slot_times'])")" "3"
check "hint first slot" "$(printf '%s' "$OUT" | jqv "d['data']['slot_times'][0]")" "09:00"
check "hint last slot" "$(printf '%s' "$OUT" | jqv "d['data']['slot_times'][-1]")" "18:00"
check "generic needs instructions" "$(printf '%s' "$OUT" | jqv "len(d['data']['instructions']) > 0")" "True"
check "generic commands" "$(printf '%s' "$OUT" | jqv "len(d['data']['commands'])")" "3"

OUT="$(run "$SCRIPTS/insights.py" schedule-hint --target generic --path-mode relative)"
check "relative path mode" "$(printf '%s' "$OUT" | jqv "d['data']['commands'][0]['command'].startswith('python3 scripts/insights.py')")" "True"
OUT="$(run "$SCRIPTS/insights.py" schedule-hint --target generic --path-mode skill)"
check "skill path mode" "$(printf '%s' "$OUT" | jqv "'{skillDir}/scripts/insights.py' in d['data']['commands'][0]['command']")" "True"

OUT="$(run "$SCRIPTS/insights.py" schedule-hint --target nanobot --wake 09:00-18:00 --budget 3)"
check "nanobot cron_expr fields" "$(printf '%s' "$OUT" | jqv "len(d['data']['cron_expr'].split())")" "5"
check "nanobot cron_expr hours" "$(printf '%s' "$OUT" | jqv "d['data']['cron_expr'].split()[1]")" "9,13,18"
check "nanobot message invocation" "$(printf '%s' "$OUT" | jqv "'\$daily-insight' in d['data']['message']")" "True"
check "nanobot cron_tool action" "$(printf '%s' "$OUT" | jqv "d['data']['cron_tool']['action']")" "add"
check "nanobot tz string" "$(printf '%s' "$OUT" | jqv "isinstance(d['data']['tz'], str)")" "True"

OUT="$(run "$SCRIPTS/insights.py" schedule-hint --target hermes)"
check "hermes skills" "$(printf '%s' "$OUT" | jqv "d['data']['skills']")" "['daily-insight']"
check "hermes script abs" "$(printf '%s' "$OUT" | jqv "d['data']['script'].endswith('scripts/insights.py next --format json')")" "True"
check "hermes cron_tool" "$(printf '%s' "$OUT" | jqv "d['data']['cron_tool']['tool']")" "cronjob"
OUT="$(run "$SCRIPTS/insights.py" schedule-hint --target hermes --generate)"
check "hermes no_agent" "$(printf '%s' "$OUT" | jqv "d['data']['cron_tool']['no_agent']")" "True"
check "hermes generate script" "$(printf '%s' "$OUT" | jqv "'--generate --outbox' in d['data']['script']")" "True"

# uniform scheduler contract
OUT="$(run "$SCRIPTS/insights.py" schedule-hint --target nanobot --at-time 07:15)"
check "nanobot at-time slot" "$(printf '%s' "$OUT" | jqv "d['data']['slot_times']")" "['07:15']"
check "nanobot at-time cron" "$(printf '%s' "$OUT" | jqv "d['data']['cron_expr']")" "15 7 * * *"
check "hint store key" "$(printf '%s' "$OUT" | jqv "'store' in d['data']")" "True"
check "nanobot cron_tool name" "$(printf '%s' "$OUT" | jqv "'name' in d['data']['cron_tool']")" "True"
check "hint installs nothing" "$(printf '%s' "$OUT" | jqv "d['data']['installs_nothing']")" "True"
check "step is post" "$(printf '%s' "$OUT" | jqv "d['data']['commands'][0]['step']")" "post"
check "hint add action" "$(printf '%s' "$OUT" | jqv "d['data']['action']")" "add"

OUT="$(run "$SCRIPTS/insights.py" schedule-hint --target nanobot --action disable --job daily-insight)"
check "hint disable action" "$(printf '%s' "$OUT" | jqv "d['data']['action']")" "disable"
check "hint disable installs nothing" "$(printf '%s' "$OUT" | jqv "d['data']['installs_nothing']")" "True"
check "hint disable route" "$(printf '%s' "$OUT" | jqv "any(r['via']=='webui_automations' for r in d['data']['routes'])")" "True"
OUT="$(run "$SCRIPTS/insights.py" schedule-hint --target systemd --action disable --job daily-insight)"
check "hint systemd manage" "$(printf '%s' "$OUT" | jqv "d['data']['routes'][0]['via']")" "systemd"
expect_fail "hint action needs job" "invalid_input" run "$SCRIPTS/insights.py" schedule-hint --target nanobot --action disable

OUT="$(run "$SCRIPTS/insights.py" schedule-hint --target crontab --wake 09:00-18:00 --budget 3)"
printf '%s' "$OUT" | "$PY" -c 'import json,sys
d=json.load(sys.stdin)
open("'"$TMPDIR_SMOKE"'/cron.txt","w").write("\n".join(d["data"]["install"]["lines"])+"\n")'
sh -n "$TMPDIR_SMOKE/cron.txt" 2>/dev/null && pass || fail "crontab lines not shell-parseable"
CRON_LINES="$(cat "$TMPDIR_SMOKE/cron.txt")"
case "$CRON_LINES" in *"next --format json"*) pass;; *) fail "crontab missing next";; esac
case "$CRON_LINES" in *"--outbox"*) pass;; *) fail "crontab missing --outbox";; esac
check "crontab line count" "$(printf '%s\n' "$CRON_LINES" | grep -c 'next')" "3"

OUT="$(run "$SCRIPTS/insights.py" schedule-hint --target systemd)"
check "systemd service file" "$(printf '%s' "$OUT" | jqv "'daily-insight.service' in d['data']['install']['files']")" "True"
check "systemd timer file" "$(printf '%s' "$OUT" | jqv "'daily-insight.timer' in d['data']['install']['files']")" "True"
check "systemd service command" "$(printf '%s' "$OUT" | jqv "'next --format json' in d['data']['install']['files']['daily-insight.service']")" "True"
check "systemd oncalendar" "$(printf '%s' "$OUT" | jqv "d['data']['install']['files']['daily-insight.timer'].count('OnCalendar=') >= 1")" "True"

OUT="$(run "$SCRIPTS/insights.py" schedule-hint --target launchd)"
printf '%s' "$OUT" | "$PY" -c 'import json,sys,plistlib
d=json.load(sys.stdin)
plistlib.loads(d["data"]["install"]["files"]["com.daily-insight.deliver.plist"].encode())' && pass || fail "launchd plist not valid"

# the emitted deliver command is idempotent and advances slot by slot
GEN="$(run "$SCRIPTS/insights.py" schedule-hint --target generic --path-mode abs)"
RUNCMD="$(printf '%s' "$GEN" | jqv "d['data']['commands'][0]['command']")"
eval "$RUNCMD" >/dev/null 2>&1 && pass || fail "emitted deliver command failed"
FIRST="$(eval "$RUNCMD" 2>/dev/null)"; rc=$?
check "emitted second call exit" "$rc" "0"
check "emitted second call advances" "$(printf '%s' "$FIRST" | jqv "d['data']['slot']['index']")" "1"

# ===========================================================================
section "portability"
# the frontmatter legitimately carries metadata.hermes; the prose must not name hosts
SKILL_BODY="$TMPDIR_SMOKE/skill_body.md"
"$PY" -c 'import sys
parts=open(sys.argv[1], encoding="utf-8").read().split("---", 2)
open(sys.argv[2], "w", encoding="utf-8").write(parts[2] if len(parts) > 2 else "")' \
  "$SKILL/SKILL.md" "$SKILL_BODY"
LEAKS="$(grep -RIl -e 'nanobot' -e 'hermes' -e 'claude' -e 'codex' -e 'kilo' -e '\$daily-insight' \
  "$SKILL_BODY" "$SKILL/references" "$SKILL/scripts" \
  | grep -v -e "$SKILL/references/scheduling.md" -e "$SKILL/references/hosts.md" -e "$SKILL/scripts/insights.py" || true)"
if [ -z "$LEAKS" ]; then pass; else fail "host tokens leaked into: $LEAKS"; fi
grep -q 'TODO' "$SKILL/SKILL.md" && fail "SKILL.md contains TODO" || pass
STRAY="$(find "$SKILL" -maxdepth 1 -mindepth 1 ! -name SKILL.md ! -name scripts ! -name references ! -name assets ! -name README.md ! -name LICENSE ! -name .gitignore ! -name requirements.txt ! -name tests)"
[ -z "$STRAY" ] && pass || fail "stray files in skill root: $STRAY"
[ -x "$SCRIPTS/_lib.py" ] && fail "_lib.py should not be executable" || pass
for script in init settings materials ingest insights reports; do
  [ -x "$SCRIPTS/$script.py" ] && pass || fail "$script.py is not executable"
done

# ===========================================================================
printf '\n========================================\n'
printf 'passed: %d   failed: %d\n' "$PASS" "$FAIL"
if [ "$FAIL" -ne 0 ]; then exit 1; fi
echo "smoke test OK"
