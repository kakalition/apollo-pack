#!/usr/bin/env bash
# Tier 3: opt-in live E2E for the daily-insight skill (network required).
#
# Runs the real daily flow against a configured OpenAI-compatible embeddings
# endpoint and chat endpoint. It only runs when an embedding key is present in
# the environment; otherwise it prints SKIP and exits 0.
#
# Keys come from the host environment, namespaced with the skill name:
#   DAILY_INSIGHT_EMBED_API_KEY   required to run (OpenAI-compatible embeddings)
#   DAILY_INSIGHT_CHAT_API_KEY    optional, for --generate
# Optional overrides:
#   DAILY_INSIGHT_LIVE_EMBED_PROVIDER   default openai
#   DAILY_INSIGHT_LIVE_EMBED_BASE_URL   default https://api.openai.com/v1
#   DAILY_INSIGHT_LIVE_EMBED_MODEL      default text-embedding-3-small
#   DAILY_INSIGHT_LIVE_CHAT_PROVIDER    default openai (or anthropic)
#   DAILY_INSIGHT_LIVE_CHAT_BASE_URL    default per provider
#   DAILY_INSIGHT_LIVE_CHAT_MODEL       default gpt-4o-mini (or claude-3-5-sonnet-latest)
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILL="$ROOT"
SCRIPTS="$SKILL/scripts"
FIXTURES="$ROOT/tests/fixtures"
PY="${PY:-python3}"
export PYTHONWARNINGS="ignore"

PASS=0
FAIL=0
TMP="$(mktemp -d "${TMPDIR:-/tmp}/di-live.XXXXXX")"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

pass() { PASS=$((PASS + 1)); }
fail() { FAIL=$((FAIL + 1)); printf 'FAIL: %s\n' "$*" >&2; }
section() { printf '\n== %s ==\n' "$*"; }
check() { if [ "$2" = "$3" ]; then pass; else fail "$1: expected [$3] got [$2]"; fi; }
jqv() { "$PY" -c 'import json,sys
d=json.load(sys.stdin)
print(eval(sys.argv[1]))' "$1"; }
run() { "$PY" "$@"; }

EMBED_KEY_ENV="DAILY_INSIGHT_EMBED_API_KEY"
if [ -z "${DAILY_INSIGHT_EMBED_API_KEY:-}" ]; then
  printf 'SKIP: tier 3 needs DAILY_INSIGHT_EMBED_API_KEY\n'
  exit 0
fi
CHAT_KEY_ENV=""
[ -n "${DAILY_INSIGHT_CHAT_API_KEY:-}" ] && CHAT_KEY_ENV="DAILY_INSIGHT_CHAT_API_KEY"

EMBED_PROVIDER="${DAILY_INSIGHT_LIVE_EMBED_PROVIDER:-openai}"
CHAT_PROVIDER="${DAILY_INSIGHT_LIVE_CHAT_PROVIDER:-openai}"
if [ "$EMBED_PROVIDER" = "openai" ]; then
  EMBED_BASE="${DAILY_INSIGHT_LIVE_EMBED_BASE_URL:-https://api.openai.com/v1}"
  EMBED_MODEL="${DAILY_INSIGHT_LIVE_EMBED_MODEL:-text-embedding-3-small}"
else
  printf 'SKIP: embeddings need the OpenAI-compatible API (provider=%s)\n' "$EMBED_PROVIDER"
  exit 0
fi
if [ "$CHAT_PROVIDER" = "anthropic" ]; then
  CHAT_BASE="${DAILY_INSIGHT_LIVE_CHAT_BASE_URL:-https://api.anthropic.com/v1}"
  CHAT_MODEL="${DAILY_INSIGHT_LIVE_CHAT_MODEL:-claude-3-5-sonnet-latest}"
else
  CHAT_BASE="${DAILY_INSIGHT_LIVE_CHAT_BASE_URL:-$EMBED_BASE}"
  CHAT_MODEL="${DAILY_INSIGHT_LIVE_CHAT_MODEL:-gpt-4o-mini}"
fi

DATA="$TMP/live"
export DAILY_INSIGHT_HOME="$DATA"

# ===========================================================================
section "configure remote endpoints"
run "$SCRIPTS/init.py" init >/dev/null
CHAT_ARGS=()
[ -n "$CHAT_KEY_ENV" ] && CHAT_ARGS=(--chat-api-key-env "$CHAT_KEY_ENV")
run "$SCRIPTS/settings.py" set \
  --budget 3 --wake 08:00-20:00 --dedup-threshold 1.0 \
  --embed-mode remote --embed-provider "$EMBED_PROVIDER" \
  --embed-base-url "$EMBED_BASE" --embed-model "$EMBED_MODEL" \
  --embed-api-key-env "$EMBED_KEY_ENV" \
  --chat-provider "$CHAT_PROVIDER" \
  --chat-base-url "$CHAT_BASE" --chat-model "$CHAT_MODEL" \
  ${CHAT_ARGS[@]+"${CHAT_ARGS[@]}"} >/dev/null
check "settings remote mode" "$(run "$SCRIPTS/settings.py" show | jqv "d['data']['settings']['embed_mode']")" "remote"
check "embedding key visible" "$(run "$SCRIPTS/settings.py" show | jqv "d['data']['embedding_key_available']")" "True"

# ===========================================================================
section "real ingest + semantic retrieval"
OUT="$(run "$SCRIPTS/ingest.py" ingest "$FIXTURES/paper.pdf" --material "Paper" --chunk-size 120 --chunk-overlap 0)"
check "live pdf ingest" "$(printf '%s' "$OUT" | jqv "d['data']['chunks_added'] >= 3")" "True"
OUT="$(run "$SCRIPTS/ingest.py" ingest "$FIXTURES/article.docx" --material "Article" --chunk-size 120 --chunk-overlap 0)"
check "live docx ingest" "$(printf '%s' "$OUT" | jqv "d['data']['chunks_added'] > 0")" "True"
VECTORS="$(run "$SCRIPTS/init.py" init | jqv "d['data']['vector_count']")"
CHUNKS="$(run "$SCRIPTS/reports.py" stats | jqv "d['data']['counts']['chunks']")"
check "live vectors match chunks" "$VECTORS" "$CHUNKS"
# keep only Paper in the day plan so the budget assertion is about one material
run "$SCRIPTS/materials.py" archive "Article" >/dev/null

"$PY" - "$SCRIPTS" "$DATA" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import _lib
home = Path(sys.argv[2])
conn = _lib.connect(_lib.resolve_db_path(home))
collection = _lib.open_collection(home)
row = conn.execute("SELECT id, ordinal, text FROM chunks WHERE text LIKE '%Deterministic chunk identifiers%' LIMIT 1").fetchone()
assert row is not None, "expected passage not found in ingested pdf"
material = conn.execute("SELECT id FROM materials WHERE name = 'Paper'").fetchone()["id"]
target = "%d:%d" % (material, row["ordinal"])
vector = _lib.embed_texts(conn, ["deterministic chunk identifiers reconcile vector and relational stores"])[0]
hits = [ident for ident, _ in _lib.chroma_query(collection, vector, material, 6)]
assert target in hits, "semantic query did not return the expected chunk (%s not in %s)" % (target, hits)
print("semantic retrieval OK")
PY
[ $? -eq 0 ] && pass || fail "semantic retrieval"

# ===========================================================================
section "simulate a day with the budget"
run "$SCRIPTS/materials.py" cadence "Paper" --count 3 --period day >/dev/null
PCHUNKS="$(run "$SCRIPTS/materials.py" show "Paper" | jqv "d['data']['chunk_count']")"
if [ "$PCHUNKS" -lt 3 ]; then EXPECT_DISTINCT="$PCHUNKS"; else EXPECT_DISTINCT="3"; fi
DAY="2026-01-05"
ORDINALS=""
for n in 1 2 3; do
  OUT="$(run "$SCRIPTS/insights.py" next --date "$DAY")"
  check "live next $n" "$(printf '%s' "$OUT" | jqv "d['data']['status']")" "delivered"
  check "live brief has novelty" "$(printf '%s' "$OUT" | jqv "'coverage_pct' in d['data']['novelty']")" "True"
  check "live brief has related list" "$(printf '%s' "$OUT" | jqv "isinstance(d['data']['related'], list)")" "True"
  check "live brief has prompt" "$(printf '%s' "$OUT" | jqv "len(d['data']['prompt']) > 0")" "True"
  ORDINALS="$ORDINALS $(printf '%s' "$OUT" | jqv "d['data']['chunk']['ordinal']")"
done
check "live distinct before cycling" "$(printf '%s' "$ORDINALS" | tr ' ' '\n' | grep -v '^$' | sort -u | wc -l | tr -d ' ')" "$EXPECT_DISTINCT"
check "live budget exhausted" "$(run "$SCRIPTS/insights.py" next --date "$DAY" | jqv "d['data']['status']")" "nothing_due"

# ===========================================================================
section "generate finished prose"
if [ -z "$CHAT_KEY_ENV" ]; then
  printf 'SKIP: no chat key set; --generate not exercised\n'
else
  GEN_DAY="2026-01-06"
  OUT="$(run "$SCRIPTS/insights.py" next --date "$GEN_DAY" --generate --outbox)"
  check "live generate ok" "$(printf '%s' "$OUT" | jqv "d['data']['status']")" "delivered"
  check "live insight text present" "$(printf '%s' "$OUT" | jqv "len(d['data'].get('insight_text','')) > 20")" "True"
  [ -f "$DATA/outbox/$GEN_DAY.md" ] && pass || fail "outbox file missing"
  check "live history shows generated" "$(run "$SCRIPTS/reports.py" history --limit 1 | jqv "d['data']['deliveries'][0]['generated']")" "True"
fi

# ===========================================================================
section "idempotency under concurrent triggers and config change"
CONC="$TMP/conc"
run "$SCRIPTS/init.py" init --home "$CONC" >/dev/null
run "$SCRIPTS/settings.py" set --budget 5 --dedup-threshold 1.0 --home "$CONC" >/dev/null
run "$SCRIPTS/materials.py" add --name Party --cadence-count 5 --cadence-period day --home "$CONC" >/dev/null
run "$SCRIPTS/ingest.py" ingest "$FIXTURES/article.docx" --material Party --chunk-size 200 --home "$CONC" >/dev/null
CDAY="2026-01-07"
run "$SCRIPTS/insights.py" run --date "$CDAY" --until 23:59 --home "$CONC" >/dev/null &
run "$SCRIPTS/insights.py" run --date "$CDAY" --until 23:59 --home "$CONC" >/dev/null &
wait
OUT="$(run "$SCRIPTS/reports.py" stats --home "$CONC")"
check "concurrent deliveries exactly budget" "$(printf '%s' "$OUT" | jqv "d['data']['counts']['deliveries']")" "5"
OUT="$(run "$SCRIPTS/insights.py" run --date "$CDAY" --until 23:59 --home "$CONC")"
check "concurrent rerun no-op" "$(printf '%s' "$OUT" | jqv "d['data']['delivered_count']")" "0"

run "$SCRIPTS/settings.py" set --budget 2 --home "$CONC" >/dev/null
NEXT_DAY="2026-01-08"
check "config change applies next day" "$(run "$SCRIPTS/insights.py" due --date "$NEXT_DAY" --home "$CONC" | jqv "len(d['data']['slots'])")" "2"

# ===========================================================================
printf '\n========================================\n'
printf 'passed: %d   failed: %d\n' "$PASS" "$FAIL"
if [ "$FAIL" -ne 0 ]; then exit 1; fi
echo "live e2e OK"
