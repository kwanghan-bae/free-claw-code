#!/usr/bin/env bash
# scripts/dogfood-snapshot.sh
# Archive daily /meta/report, telemetry counts, suggestion summary, test state.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DATE="$(date -u +%Y-%m-%d)"
OUT="docs/superpowers/dogfood/$DATE"
mkdir -p "$OUT"

step() { printf "[%s] %s\n" "$(date +%H:%M:%S)" "$1"; }

step "1/4 /meta/report HTML"
if curl -sf http://127.0.0.1:7801/meta/report -o "$OUT/meta-report.html"; then
  printf "  saved meta-report.html (%s bytes)\n" "$(wc -c < "$OUT/meta-report.html")"
else
  printf "  ⚠ /meta/report 실패 — 사이드카 기동 여부 확인\n"
fi

step "2/4 telemetry counts"
DB="$HOME/.free-claw-router/telemetry.db"
if [ -f "$DB" ]; then
  python - <<PY > "$OUT/telemetry-counts.json"
import json, sqlite3
conn = sqlite3.connect("$DB")
out = {}
for t in ("spans", "events", "evaluations"):
    try:
        out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    except Exception as e:
        out[t] = f"err: {e}"
try:
    out["events_by_kind_24h"] = dict(conn.execute(
        "SELECT kind, COUNT(*) FROM events "
        "WHERE ts >= DATE('now','-1 day') GROUP BY kind"
    ).fetchall())
except Exception as e:
    out["events_by_kind_24h"] = f"err: {e}"
try:
    out["routing_decisions_24h"] = conn.execute(
        "SELECT COUNT(*) FROM events WHERE kind='routing_decision' AND ts >= DATE('now','-1 day')"
    ).fetchone()[0]
except Exception:
    out["routing_decisions_24h"] = 0
print(json.dumps(out, indent=2, ensure_ascii=False))
PY
  printf "  saved telemetry-counts.json\n"
else
  printf "  (no telemetry.db yet)\n"
  echo "{}" > "$OUT/telemetry-counts.json"
fi

step "3/4 suggestions summary"
SUG="$HOME/.free-claw-router/meta_suggestions.json"
if [ -f "$SUG" ]; then
  python - <<PY > "$OUT/suggestions-summary.json"
import json
from collections import Counter
try:
    items = json.loads(open("$SUG").read()) or []
except Exception:
    items = []
by_target = Counter(i.get("target_file", "?") for i in items)
by_edit_type = Counter(i.get("edit_type", "?") for i in items)
print(json.dumps({
    "total": len(items),
    "by_target_file": dict(by_target),
    "by_edit_type": dict(by_edit_type),
}, indent=2, ensure_ascii=False))
PY
  printf "  saved suggestions-summary.json\n"
else
  printf "  (no meta_suggestions.json yet)\n"
  echo "{\"total\": 0}" > "$OUT/suggestions-summary.json"
fi

step "4/4 test state"
{
  printf "=== cargo test (rust/) ===\n"
  (cd rust && cargo test --workspace --quiet 2>&1 | tail -25) || true
  printf "\n=== pytest (free-claw-router/) ===\n"
  (cd free-claw-router && uv run pytest -q 2>&1 | tail -20) || true
} > "$OUT/tests.log"
printf "  saved tests.log\n"

printf "\n✅ snapshot → %s\n" "$OUT"
