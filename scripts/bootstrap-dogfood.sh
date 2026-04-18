#!/usr/bin/env bash
# scripts/bootstrap-dogfood.sh
# Idempotent environment check for P5 L2 dogfood.
# Usage:  ./scripts/bootstrap-dogfood.sh [--restart]
#   --restart  also (re)start the sidecar in the background
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

step() { printf "\n[%s] %s\n" "$(date +%H:%M:%S)" "$1"; }
fail() { printf "❌ %s\n" "$1" >&2; exit 1; }
ok()   { printf "✓ %s\n" "$1"; }

RESTART=0
for arg in "$@"; do
  case "$arg" in
    --restart) RESTART=1 ;;
    -h|--help)
      cat <<HELP
bootstrap-dogfood.sh — environment check for P5 L2 dogfood

Checks:
  1. .env required API keys (OPENROUTER_API_KEY, GROQ_API_KEY, ZAI_API_KEY, CEREBRAS_API_KEY)
  2. mempalace CLI init
  3. OpenSpace MCP reachable
  4. Sidecar /healthz (use --restart to relaunch)
  5. Rust CLI release build
  6. OPENAI_BASE_URL export reminder
  7. Telemetry DB

Flags:
  --restart   (re)launch the sidecar in the background
HELP
      exit 0 ;;
  esac
done

step "1/7 .env 필수 키 점검"
if [ ! -f .env ]; then
  if [ ! -f .env.template ]; then
    cat > .env.template <<'EOF'
# 필수 (Track C affinity 헤더를 쓰지 않아도 P0 라우팅엔 필요)
OPENROUTER_API_KEY=
GROQ_API_KEY=
ZAI_API_KEY=
CEREBRAS_API_KEY=
# 선택
ANTHROPIC_API_KEY=
EOF
  fi
  fail ".env 미존재 — .env.template 참고하여 키 채운 뒤 재실행."
fi
# shellcheck disable=SC1091
set -a; source .env; set +a
missing=()
for k in OPENROUTER_API_KEY GROQ_API_KEY ZAI_API_KEY CEREBRAS_API_KEY; do
  if [ -z "${!k:-}" ]; then missing+=("$k"); fi
done
if [ ${#missing[@]} -gt 0 ]; then
  fail ".env 키 비어있음: ${missing[*]}"
fi
ok ".env 4개 필수 키 채워짐"

step "2/7 mempalace init"
if ! command -v mempalace >/dev/null 2>&1; then
  fail "mempalace CLI 미설치 — uv pip install mempalace 또는 setup 확인"
fi
mempalace init "$HOME/projects" 2>/dev/null || ok "mempalace palace 이미 초기화됨"

step "3/7 OpenSpace MCP 점검"
if ! python -c "import openspace.mcp_server" 2>/dev/null; then
  fail "OpenSpace MCP import 실패 — pip install openspace 또는 PYTHONPATH 확인"
fi
ok "openspace.mcp_server import 가능"

step "4/7 사이드카 /healthz"
sidecar_up() {
  curl -sf -o /dev/null http://127.0.0.1:7801/healthz
}
if sidecar_up; then
  ok "사이드카 기동 중"
else
  if [ "$RESTART" = "1" ]; then
    printf "  --restart 지정, 백그라운드 기동 시도\n"
    (cd free-claw-router && nohup uv run uvicorn router.server.openai_compat:app --port 7801 >/tmp/fcr.log 2>&1 &) >/dev/null
    for _ in 1 2 3 4 5 6 7 8; do
      if sidecar_up; then break; fi
      sleep 1
    done
    if sidecar_up; then
      ok "사이드카 백그라운드 기동 성공 (log: /tmp/fcr.log)"
    else
      fail "기동 실패 — /tmp/fcr.log 확인"
    fi
  else
    fail "사이드카 응답 없음. 별도 터미널에서 기동하거나 --restart 재실행:
  cd free-claw-router && uv run uvicorn router.server.openai_compat:app --port 7801"
  fi
fi

step "5/7 Rust CLI 빌드 (release)"
if ! (cd rust && cargo build --release -p rusty-claude-cli --quiet); then
  fail "rust build 실패"
fi
ok "rust/target/release/claw 준비됨"

step "6/7 OPENAI_BASE_URL"
if [ -n "${OPENAI_BASE_URL:-}" ]; then
  ok "OPENAI_BASE_URL=$OPENAI_BASE_URL (이미 설정)"
else
  printf "  ⚠ 현재 쉘에 export 필요:\n"
  printf "    export OPENAI_BASE_URL=http://127.0.0.1:7801\n"
fi

step "7/7 텔레메트리 DB"
DB="$HOME/.free-claw-router/telemetry.db"
if [ -f "$DB" ]; then
  size=$(stat -f%z "$DB" 2>/dev/null || stat -c%s "$DB")
  ok "$DB ($size bytes)"
else
  printf "  (첫 요청 시 자동 생성)\n"
fi

printf "\n✅ 부트스트랩 완료. 다음:\n"
printf "  1. export OPENAI_BASE_URL=http://127.0.0.1:7801 (필요 시)\n"
printf "  2. ./rust/target/release/claw 로 첫 세션 시작\n"
printf "  3. 하루 끝에 ./scripts/dogfood-snapshot.sh 실행\n"
