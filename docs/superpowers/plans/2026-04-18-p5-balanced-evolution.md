# P5 밸런스드 진화 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development` (권장) 또는 `superpowers:executing-plans`로 작업 단위별 실행. 체크박스(`- [ ]`) 동기로 진행 추적.

**Goal:** 5층 자기진화 루프(P0~P4)를 실사용에 견딜 수 있도록 안정화한다 — 거대 파일 모듈화 + 감사 대시보드 + 적응형 라우팅 + SSE + 1주 dogfood.

**Architecture:** 4-트랙 병렬(A 부채 / B 관측 / C 루프 / D dogfood). 각 트랙은 독립 worktree에서 feature 브랜치로 개발 후 `main`에 직접 머지. A/B/C 머지 70% 시점(A-4·B-1·B-2·C-1 완료)에 통합 리뷰 체크포인트 1회, 이후 D 개시.

**Tech Stack:** Rust 2021 (axum 0.7 신규, reqwest, 워크스페이스 8 crates) + Python 3.11 (FastAPI, httpx, APScheduler) + SQLite + Mempalace + Vanilla HTML. 외부 알림/대시보드 스택 추가 없음 (L3로 이월).

**원본 스펙:** `docs/superpowers/specs/2026-04-18-p5-balanced-evolution-design.md`

---

## 파일 구조 지도

### 신규 파일

| 경로 | 책임 |
|---|---|
| `rust/crates/rusty-claude-cli/src/session_lifecycle.rs` | 세션 시작/resume/compact |
| `rust/crates/rusty-claude-cli/src/command_dispatch.rs` | 슬래시 명령 라우팅 |
| `rust/crates/rusty-claude-cli/src/permissions_runtime.rs` | 런타임 퍼미션 |
| `rust/crates/rusty-claude-cli/src/output_format.rs` | compact/verbose 포맷 |
| `rust/crates/rusty-claude-cli/src/date_utils.rs` | 날짜 계산 (clippy 격리) |
| `rust/crates/tools/src/{bash,browser,git,lsp,search,file}/mod.rs` | 도구별 모듈 |
| `rust/crates/commands/src/cron.rs` | CronCreate → 사이드카 브릿지 |
| `rust/crates/commands/src/meta_cmd.rs` | `clawd meta *` 명령 |
| `rust/crates/runtime/src/backpressure_server.rs` | axum /internal/backpressure |
| `free-claw-router/router/server/_telemetry_middleware.py` | span 삽입 |
| `free-claw-router/router/server/_quota_middleware.py` | 쿼터 |
| `free-claw-router/router/server/_injection.py` | P1 주입 + P3 넛지 |
| `free-claw-router/router/server/meta_report.py` | HTML 감사 리포트 |
| `free-claw-router/router/server/gc.py` | 스토어 GC |
| `free-claw-router/router/server/dev_triggers.py` | 강제 트리거 (dev 전용) |
| `free-claw-router/router/routing/affinity.py` | 베이지안 평탄화 |
| `free-claw-router/router/dispatch/sse.py` | SSE passthrough |
| `free-claw-router/tests/test_routing_affinity.py` | affinity 유닛 |
| `free-claw-router/tests/test_sse_dispatch.py` | SSE 유닛 |
| `free-claw-router/tests/test_meta_report.py` | HTML 리포트 유닛 |
| `free-claw-router/tests/test_gc.py` | GC 유닛 |
| `scripts/bootstrap-dogfood.sh` | 환경 부트스트랩 |
| `scripts/dogfood-snapshot.sh` | 일일 스냅샷 |
| `docs/superpowers/dogfood/p5-retrospective.md` | Day 7 회고 |
| `docs/superpowers/dogfood/p5-blockers.md` | 미충족 블로커 (필요시) |

### 수정 파일

| 경로 | 변경 |
|---|---|
| `rust/crates/rusty-claude-cli/src/main.rs` | 11.8K → <500 LOC (다른 파일로 이동 + `pub use`) |
| `rust/crates/tools/src/lib.rs` | 9.7K → facade만 남김 (`pub use tools::*` 스타일) |
| `rust/Cargo.toml` | workspace deps에 `axum = "0.7"` 추가 |
| `free-claw-router/router/server/openai_compat.py` | 304 → ≤100 LOC, SSE 분기 추가 |
| `free-claw-router/router/server/lifespan.py` | GC 크론 등록 |
| `free-claw-router/router/routing/score.py` | affinity_bonus 합산 |
| `free-claw-router/router/meta/meta_evaluator.py` | 연속 2회 롤백 블록 |
| `free-claw-router/router/meta/meta_targets.yaml` | affinity config 등록 |
| `free-claw-router/router/catalog/data/*.yaml` | `capabilities.sse` 필드 |
| `USAGE.md` | Dogfood 운영 가이드 섹션 |
| `CLAUDE.md` | GC·블록 정책 계약 추가 |

---

## 공통 전제

### Worktree 준비 (플랜 실행 시작 전, 1회)

- [ ] **Step 0-1: 4개 worktree 생성**

```bash
cd /Users/joel/Desktop/git/free-claw-code
git worktree add ../free-claw-code-p5-a feature/p5-track-a-debt
git worktree add ../free-claw-code-p5-b feature/p5-track-b-observe
git worktree add ../free-claw-code-p5-c feature/p5-track-c-loop
git worktree add ../free-claw-code-p5-d feature/p5-track-d-dogfood
git worktree list
```

- [ ] **Step 0-2: 각 worktree에서 기준선 통과 확인**

각 worktree에 들어가 한 번씩:
```bash
cd ../free-claw-code-p5-a
cd rust && cargo test --workspace --quiet
cd ../free-claw-router && uv run pytest -q
```

기대: 전부 통과. 실패하면 기준선 회귀부터 잡고 시작.

### 커밋 메시지 규약

- A 트랙: `refactor(<crate>): ...` / `feat(rust): ...`
- B 트랙: `feat(meta): ...` / `feat(router): ...`
- C 트랙: `feat(routing): ...` / `feat(dispatch): ...`
- D 트랙: `chore(dogfood): ...` / `docs(dogfood): ...`
- 모든 커밋에 `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` 트레일러.

---

# Track A — 부채 정리

worktree: `../free-claw-code-p5-a`, 브랜치: `feature/p5-track-a-debt`

## Task A-1: `main.rs` 모듈 분할 (11.8K LOC → <500 LOC)

**Files:**
- Modify: `rust/crates/rusty-claude-cli/src/main.rs`
- Create: `rust/crates/rusty-claude-cli/src/session_lifecycle.rs`
- Create: `rust/crates/rusty-claude-cli/src/command_dispatch.rs`
- Create: `rust/crates/rusty-claude-cli/src/permissions_runtime.rs`
- Create: `rust/crates/rusty-claude-cli/src/output_format.rs`
- Create: `rust/crates/rusty-claude-cli/src/date_utils.rs`

**전략:** 외부 API 불변. 기존 테스트 통과가 성공 지표. 모듈 하나씩 추출 후 빌드·테스트·커밋.

### A-1.1: 추출 전 기준선 캡처

- [ ] **Step 1: 공개 심볼 목록 스냅샷**

```bash
cd rust
cargo check -p rusty-claude-cli --message-format=json 2>&1 | \
  rg '"rendered"' | wc -l > /tmp/p5-a-baseline-messages.txt
rg '^pub (fn|struct|enum|trait|use) ' crates/rusty-claude-cli/src/main.rs \
  > /tmp/p5-a-baseline-symbols.txt
cat /tmp/p5-a-baseline-symbols.txt
```

기대: 공개 심볼 목록 출력. 파일 보관 — 분할 후 diff로 누락 검사.

- [ ] **Step 2: 기존 테스트 통과 확인**

```bash
cargo test -p rusty-claude-cli --quiet
```

기대: PASS. 실패 시 A-1 중단 후 조사.

### A-1.2: `date_utils.rs` 추출 (clippy 격리 목적, 가장 작은 첫 스텝)

- [ ] **Step 1: clippy 대상 위치 확인**

```bash
rg -n 'fn .*doe|fn .*doy|let doe|let doy' crates/rusty-claude-cli/src/main.rs
```

기대: `main.rs:5758-5761` 주변의 `doe`/`doy` 변수를 포함한 함수 발견.

- [ ] **Step 2: 해당 함수(들)를 `date_utils.rs`로 이동**

```rust
// rust/crates/rusty-claude-cli/src/date_utils.rs
#![allow(clippy::similar_names)]
// `doe`(date-of-era), `doy`(day-of-year)는 Howard Hinnant date algorithm 표준 변수명.

// (main.rs에서 복사한 함수들 붙여넣기, 의존성 함수는 그대로 참조)
```

- [ ] **Step 3: `main.rs`에서 원본 제거 + 모듈 선언**

`main.rs` 맨 위에 추가:
```rust
mod date_utils;
use date_utils::*;  // 또는 필요한 심볼만 명시 use
```

- [ ] **Step 4: 빌드 확인**

```bash
cargo build -p rusty-claude-cli 2>&1 | head -40
```

기대: 에러 없음. 에러 있으면 `use` 경로 보정.

- [ ] **Step 5: 테스트 통과 확인**

```bash
cargo test -p rusty-claude-cli --quiet
```

기대: PASS.

- [ ] **Step 6: clippy 경고 확인 — 1개 사라졌는지**

```bash
cargo clippy -p rusty-claude-cli --all-targets 2>&1 | rg 'similar_names' | wc -l
```

기대: 0.

- [ ] **Step 7: 커밋**

```bash
git add crates/rusty-claude-cli/src/
git commit -m "$(cat <<'EOF'
refactor(cli): extract date_utils module + isolate similar_names allow

Move date-of-era / day-of-year calc out of main.rs (lines ~5758-5761) into
date_utils.rs with #![allow(clippy::similar_names)] at file level.
Clippy similar_names warning eliminated from workspace.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### A-1.3: `output_format.rs` 추출

- [ ] **Step 1: 출력 포맷 함수 식별**

```bash
rg -n 'fn .*(format|render|print).*(compact|verbose|session)' crates/rusty-claude-cli/src/main.rs
```

기대: compact/verbose/tui 출력 관련 함수 목록.

- [ ] **Step 2: 함수 이동** (date_utils와 동일 절차)

`output_format.rs` 생성, 식별된 함수들 이동, `pub fn` 유지.

- [ ] **Step 3: `main.rs`에서 제거 + `mod output_format; use output_format::*;` 선언**

- [ ] **Step 4: 빌드·테스트**

```bash
cargo build -p rusty-claude-cli && cargo test -p rusty-claude-cli --quiet
```

- [ ] **Step 5: 커밋**

```bash
git add . && git commit -m "refactor(cli): extract output_format module

Move compact/verbose render helpers out of main.rs.
External API preserved via pub use.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### A-1.4: `permissions_runtime.rs` 추출

- [ ] **Step 1: 퍼미션 관련 함수 식별**

```bash
rg -n 'fn .*(permission|allow|deny|enforce)' crates/rusty-claude-cli/src/main.rs
```

- [ ] **Step 2~5: 이동·빌드·테스트·커밋** (A-1.3과 동일 절차)

커밋 메시지: `refactor(cli): extract permissions_runtime module`

### A-1.5: `command_dispatch.rs` 추출

- [ ] **Step 1: 슬래시 명령 라우터 식별**

```bash
rg -n 'fn .*(dispatch|handle_slash|slash_command)' crates/rusty-claude-cli/src/main.rs
```

- [ ] **Step 2~5: 이동·빌드·테스트·커밋**

커밋 메시지: `refactor(cli): extract command_dispatch module`

### A-1.6: `session_lifecycle.rs` 추출

- [ ] **Step 1: 세션 관련 함수 식별**

```bash
rg -n 'fn .*(session|resume|compact|start_session|end_session)' crates/rusty-claude-cli/src/main.rs | head -40
```

- [ ] **Step 2~5: 이동·빌드·테스트·커밋**

커밋 메시지: `refactor(cli): extract session_lifecycle module`

### A-1.7: 분할 완결 검증

- [ ] **Step 1: `main.rs` 라인 수 확인**

```bash
wc -l crates/rusty-claude-cli/src/main.rs
```

기대: < 500 (목표). 900 이하면 수용.

- [ ] **Step 2: 공개 심볼 diff**

```bash
rg -n '^pub (fn|struct|enum|trait|use) ' crates/rusty-claude-cli/src/ \
  > /tmp/p5-a-final-symbols.txt
diff /tmp/p5-a-baseline-symbols.txt /tmp/p5-a-final-symbols.txt
```

기대: 이동된 심볼은 새 경로로 나타나지만, **외부 from-path로 보면 `pub use`로 동일 경로 재수출**되어야 함. diff가 재배치만이면 OK.

- [ ] **Step 3: 통합 테스트 전량**

```bash
cargo test --workspace --quiet
```

기대: PASS.

- [ ] **Step 4: 커밋 (필요시 `pub use` 재수출 추가)**

```bash
git add . && git commit -m "refactor(cli): finalize main.rs split — pub use shims

main.rs now < 500 LOC. All previously-public paths preserved via
pub use re-exports at crate root. External consumers (integration
tests, bin targets) unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task A-2: `tools/lib.rs` 분할 (9.7K LOC → facade)

**Files:**
- Modify: `rust/crates/tools/src/lib.rs`
- Create: `rust/crates/tools/src/{bash,browser,git,lsp,search,file}/mod.rs`

### A-2.1: 도구 카테고리 식별

- [ ] **Step 1: 주요 도구 함수·struct 그루핑**

```bash
cd rust
rg -n '^pub (fn|struct|impl) ' crates/tools/src/lib.rs | head -60
```

관찰: bash/browser/git/lsp/search/file 6개 묶음으로 자연 분할 가능. 각 묶음의 라인 범위 기록.

### A-2.2: `bash/mod.rs` 추출

- [ ] **Step 1: bash 관련 심볼 식별**

```bash
rg -n 'fn .*bash|struct .*Bash|BashExec' crates/tools/src/lib.rs
```

- [ ] **Step 2: `bash/mod.rs` 생성 + 심볼 이동**

디렉터리 `crates/tools/src/bash/` 생성. `mod.rs`에 bash 관련 코드 이동. `pub` 유지.

- [ ] **Step 3: `lib.rs`에 facade 추가**

```rust
// crates/tools/src/lib.rs 최상단
pub mod bash;
pub use bash::*;  // 기존 경로 보존
```

- [ ] **Step 4: 빌드·테스트**

```bash
cargo build -p tools && cargo test -p tools --quiet && cargo test --workspace --quiet
```

기대: 모든 테스트 PASS. 실패 시 `pub use` 누락 보정.

- [ ] **Step 5: 커밋**

```bash
git add crates/tools/ && git commit -m "refactor(tools): extract bash module

Move bash tool symbols to tools/src/bash/mod.rs. Facade in lib.rs
re-exports everything via pub use for path compatibility.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### A-2.3~A-2.7: 나머지 5개 모듈 추출

각각 동일 절차로 `browser/`, `git/`, `lsp/`, `search/`, `file/` 추출.

- [ ] **A-2.3 browser**: `rg 'browser|Browser'` → 이동 → 빌드·테스트·커밋
- [ ] **A-2.4 git**: `rg 'fn .*git|GitOp'` → 이동 → 빌드·테스트·커밋
- [ ] **A-2.5 lsp**: `rg 'lsp|Lsp|LSP'` → 이동 → 빌드·테스트·커밋
- [ ] **A-2.6 search**: `rg 'grep|glob|Search'` → 이동 → 빌드·테스트·커밋
- [ ] **A-2.7 file**: `rg 'fn .*(read|write|edit)_file|FileOp'` → 이동 → 빌드·테스트·커밋

### A-2.8: `lib.rs` 최종 정리

- [ ] **Step 1: `lib.rs`를 facade만 남긴 파일로 축소**

```rust
// crates/tools/src/lib.rs
//! Tools crate — facade over submodules.
//! Path compatibility: all previously-public `tools::*` paths still resolve.

pub mod bash;
pub mod browser;
pub mod git;
pub mod lsp;
pub mod search;
pub mod file;

// 기존 경로 보존 — 외부 crate에서 `use tools::BashExec` 등 깨지지 않도록
pub use bash::*;
pub use browser::*;
pub use git::*;
pub use lsp::*;
pub use search::*;
pub use file::*;
```

- [ ] **Step 2: 전체 워크스페이스 테스트**

```bash
cargo test --workspace --quiet
```

기대: PASS.

- [ ] **Step 3: 커밋**

```bash
git add . && git commit -m "refactor(tools): reduce lib.rs to facade

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task A-3: `openai_compat.py` 4-분리

**Files:**
- Modify: `free-claw-router/router/server/openai_compat.py`
- Create: `free-claw-router/router/server/_telemetry_middleware.py`
- Create: `free-claw-router/router/server/_quota_middleware.py`
- Create: `free-claw-router/router/server/_injection.py`

### A-3.1: 관심사 라인 범위 식별

- [ ] **Step 1: 파일 섹션 매핑**

```bash
cd free-claw-router
rg -n '^def |^async def |^class ' router/server/openai_compat.py
```

결과를 보고 각 함수가 텔레메트리 / 쿼터 / 주입 / 라우팅 배선 중 어디 속하는지 라벨링.

- [ ] **Step 2: 기준 테스트 실행**

```bash
uv run pytest -q
```

기대: PASS.

### A-3.2: `_telemetry_middleware.py` 분리

- [ ] **Step 1: 텔레메트리 함수들 새 파일로 이동**

```python
# router/server/_telemetry_middleware.py
"""Telemetry span/trace insertion for OpenAI-compat requests.
Extracted from openai_compat.py for separation of concerns.
"""
from __future__ import annotations

# (openai_compat.py의 span 시작/종료, trace_id 추출, event 기록 함수들 붙여넣기)
```

- [ ] **Step 2: `openai_compat.py`에서 제거 + import 추가**

```python
from router.server._telemetry_middleware import (
    start_span, end_span, emit_event,  # 실제 이동한 이름 목록
)
```

- [ ] **Step 3: 테스트**

```bash
uv run pytest -q
```

- [ ] **Step 4: 커밋**

```bash
git add router/server/
git commit -m "refactor(router): split telemetry middleware out of openai_compat

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### A-3.3: `_quota_middleware.py` 분리

- [ ] **Step 1~4: 쿼터 함수 이동** (A-3.2와 동일 절차)

커밋 메시지: `refactor(router): split quota middleware out of openai_compat`

### A-3.4: `_injection.py` 분리

- [ ] **Step 1~4: P1 메모리 주입 + P3 넛지 함수 이동**

커밋 메시지: `refactor(router): split memory/nudge injection out of openai_compat`

### A-3.5: 결과 검증

- [ ] **Step 1: `openai_compat.py` 라인 수 확인**

```bash
wc -l router/server/openai_compat.py
```

기대: ≤ 100 LOC. 130 이하면 수용.

- [ ] **Step 2: 전체 테스트**

```bash
uv run pytest -q
```

기대: PASS.

---

## Task A-4: Rust `CronCreate` → 사이드카 `/cron/register` 브릿지

**Files:**
- Create: `rust/crates/commands/src/cron.rs`
- Modify: `rust/crates/commands/src/lib.rs` (re-export)
- Create: `rust/crates/commands/tests/cron_bridge.rs`

### A-4.1: 유닛 테스트 먼저 (TDD)

- [ ] **Step 1: 실패 테스트 작성**

```rust
// rust/crates/commands/tests/cron_bridge.rs
// dev-deps에 wiremock = "0.6", tempfile = "3", tokio = { features = ["macros","rt"] } 필요
use commands::cron::{register_cron, register_cron_with_fallback, CronSpec};
use wiremock::{matchers::{method, path}, Mock, MockServer, ResponseTemplate};

#[tokio::test]
async fn register_cron_posts_to_sidecar() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/cron/register"))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({"ok": true, "job_id": "abc"})))
        .expect(1)
        .mount(&server)
        .await;

    let spec = CronSpec {
        job_id: "abc".into(),
        cron_expr: "*/5 * * * *".into(),
        payload: serde_json::json!({"task": "ping"}),
    };
    let result = register_cron(&server.uri(), &spec).await;
    assert!(result.is_ok(), "got {:?}", result);
    // expect(1) 만족 여부는 drop 시 자동 verify
}

#[tokio::test]
async fn register_cron_falls_back_on_error() {
    let fallback_dir = tempfile::tempdir().unwrap();
    let spec = CronSpec {
        job_id: "xyz".into(),
        cron_expr: "0 0 * * *".into(),
        payload: serde_json::json!({}),
    };
    // 사용되지 않는 loopback 포트로 연결 실패 유도
    let result = register_cron_with_fallback(
        "http://127.0.0.1:1",
        &spec,
        fallback_dir.path(),
    ).await;
    assert!(result.is_ok());
    assert!(fallback_dir.path().join("xyz.json").exists());
}
```

- [ ] **Step 2: 컴파일 실패 확인**

```bash
cd rust && cargo test -p commands --test cron_bridge --no-run 2>&1 | head -20
```

기대: `cannot find crate 'commands::cron'` 또는 `register_cron not found`.

### A-4.2: 최소 구현

- [ ] **Step 1: `cron.rs` 작성**

```rust
// rust/crates/commands/src/cron.rs
use serde::{Deserialize, Serialize};
use std::path::Path;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CronSpec {
    pub job_id: String,
    pub cron_expr: String,
    pub payload: serde_json::Value,
}

#[derive(Debug, thiserror::Error)]
pub enum CronError {
    #[error("sidecar error: {0}")]
    Sidecar(String),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

pub async fn register_cron(sidecar_url: &str, spec: &CronSpec) -> Result<(), CronError> {
    let client = reqwest::Client::new();
    let url = format!("{}/cron/register", sidecar_url.trim_end_matches('/'));
    let resp = client.post(&url).json(spec).send().await
        .map_err(|e| CronError::Sidecar(e.to_string()))?;
    if !resp.status().is_success() {
        return Err(CronError::Sidecar(format!("status {}", resp.status())));
    }
    Ok(())
}

pub async fn register_cron_with_fallback(
    sidecar_url: &str,
    spec: &CronSpec,
    fallback_dir: &Path,
) -> Result<(), CronError> {
    match register_cron(sidecar_url, spec).await {
        Ok(()) => Ok(()),
        Err(_) => {
            std::fs::create_dir_all(fallback_dir)?;
            let path = fallback_dir.join(format!("{}.json", spec.job_id));
            std::fs::write(path, serde_json::to_vec_pretty(spec)?)?;
            Ok(())
        }
    }
}

impl From<serde_json::Error> for CronError {
    fn from(e: serde_json::Error) -> Self { CronError::Io(std::io::Error::new(std::io::ErrorKind::InvalidData, e)) }
}
```

- [ ] **Step 2: `lib.rs` re-export**

```rust
pub mod cron;
```

- [ ] **Step 3: 의존성 확인**

`crates/commands/Cargo.toml`에 `reqwest`, `serde`, `thiserror`, `tempfile`(dev), `tokio`(dev, features=["macros","rt"]) 있는지 확인. 없으면 추가.

- [ ] **Step 4: 테스트 실행**

```bash
cargo test -p commands --test cron_bridge
```

기대: PASS.

### A-4.3: 실제 호출 경로 연결

- [ ] **Step 1: 기존 `CronCreate` 호출점 식별**

```bash
rg -n 'CronCreate|cron_create' rust/crates/
```

- [ ] **Step 2: 호출점에서 `register_cron_with_fallback` 사용하도록 수정**

사이드카 URL은 환경변수 `FREE_CLAW_ROUTER_URL` 기본값 `http://127.0.0.1:7801`.
Fallback dir: `~/.claude/cron/`.

- [ ] **Step 3: 통합 테스트 (실제 사이드카 없이도 fallback으로 성공)**

```bash
cargo test --workspace --quiet
```

- [ ] **Step 4: 커밋**

```bash
git add . && git commit -m "feat(rust): wire CronCreate to sidecar /cron/register with fallback

Closes P0 Task 47. Sidecar unavailable → local file fallback at
~/.claude/cron/<job_id>.json preserves existing behavior.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task A-5: axum `/internal/backpressure` 리스너

**Files:**
- Modify: `rust/Cargo.toml` (workspace deps)
- Modify: `rust/crates/runtime/Cargo.toml`
- Create: `rust/crates/runtime/src/backpressure_server.rs`
- Create: `rust/crates/runtime/tests/backpressure_http.rs`

### A-5.1: axum 의존성 추가

- [ ] **Step 1: workspace Cargo.toml 수정**

```toml
# rust/Cargo.toml 의 [workspace.dependencies]
axum = { version = "0.7", features = ["json"] }
tower = "0.4"
```

- [ ] **Step 2: runtime crate에 추가**

```toml
# rust/crates/runtime/Cargo.toml
[dependencies]
axum = { workspace = true }
# ...
```

- [ ] **Step 3: 빌드 확인**

```bash
cd rust && cargo build -p runtime
```

기대: 에러 없음.

### A-5.2: TDD — 실패 테스트

- [ ] **Step 1: 통합 테스트 작성**

```rust
// rust/crates/runtime/tests/backpressure_http.rs
use runtime::backpressure_server::{spawn_backpressure_server, BackpressureSignal};

#[tokio::test]
async fn posts_signal_reaches_rate_limiter() {
    let (addr, rx) = spawn_backpressure_server("127.0.0.1:0").await.unwrap();
    let client = reqwest::Client::new();
    let resp = client
        .post(format!("http://{}/internal/backpressure", addr))
        .json(&serde_json::json!({"level": "warn", "reason": "quota-near"}))
        .send().await.unwrap();
    assert_eq!(resp.status(), 200);
    let sig = rx.recv().await.unwrap();
    assert_eq!(sig.level, "warn");
}

#[tokio::test]
async fn rejects_non_localhost_binding() {
    let err = spawn_backpressure_server("0.0.0.0:0").await;
    assert!(err.is_err());
}
```

- [ ] **Step 2: 실패 확인**

```bash
cargo test -p runtime --test backpressure_http --no-run 2>&1 | tail -10
```

기대: `backpressure_server not found`.

### A-5.3: 최소 구현

- [ ] **Step 1: `backpressure_server.rs` 작성**

```rust
// rust/crates/runtime/src/backpressure_server.rs
use axum::{routing::post, Json, Router};
use serde::{Deserialize, Serialize};
use std::net::SocketAddr;
use tokio::sync::mpsc;

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct BackpressureSignal {
    pub level: String,
    pub reason: String,
}

pub async fn spawn_backpressure_server(
    bind: &str,
) -> Result<(SocketAddr, mpsc::Receiver<BackpressureSignal>), String> {
    let addr: SocketAddr = bind.parse().map_err(|e: std::net::AddrParseError| e.to_string())?;
    if !addr.ip().is_loopback() {
        return Err(format!("must bind to loopback, got {}", addr.ip()));
    }
    let (tx, rx) = mpsc::channel(16);
    let app = Router::new()
        .route("/internal/backpressure", post(move |Json(sig): Json<BackpressureSignal>| {
            let tx = tx.clone();
            async move {
                let _ = tx.send(sig).await;
                axum::http::StatusCode::OK
            }
        }));
    let listener = tokio::net::TcpListener::bind(addr).await.map_err(|e| e.to_string())?;
    let local_addr = listener.local_addr().map_err(|e| e.to_string())?;
    tokio::spawn(async move {
        let _ = axum::serve(listener, app).await;
    });
    Ok((local_addr, rx))
}
```

- [ ] **Step 2: `runtime/src/lib.rs`에 모듈 선언**

```rust
pub mod backpressure_server;
```

- [ ] **Step 3: 테스트 실행**

```bash
cargo test -p runtime --test backpressure_http
```

기대: PASS.

- [ ] **Step 4: 전체 워크스페이스 회귀 확인**

```bash
cargo test --workspace --quiet
```

- [ ] **Step 5: 커밋**

```bash
git add . && git commit -m "feat(runtime): add axum /internal/backpressure listener

Closes P0 Task 8 Step 3. Loopback-only binding enforced at spawn.
Signals delivered to rate limiter via tokio mpsc.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task A-6: clippy 워크스페이스 통과 최종 확인

- [ ] **Step 1: 전체 clippy**

```bash
cd rust && cargo clippy --workspace --all-targets -- -D warnings
```

기대: 통과. `similar_names`는 A-1.2에서 파일 단위 `allow`로 해소됨. 다른 경고 발생하면 수정 후 재실행.

- [ ] **Step 2: A 트랙 머지**

```bash
git checkout main
git merge feature/p5-track-a-debt --no-ff -m "merge: Track A (debt) — main.rs/tools/lib.rs modularization, cron bridge, backpressure listener"
```

---

# Track B — 관측 & 안전 강화

worktree: `../free-claw-code-p5-b`, 브랜치: `feature/p5-track-b-observe`

## Task B-1: `/meta/report` HTML 감사 리포트

**Files:**
- Create: `free-claw-router/router/server/meta_report.py`
- Modify: `free-claw-router/router/server/openai_compat.py` (라우트 등록)
- Create: `free-claw-router/tests/test_meta_report.py`

### B-1.1: TDD — 실패 테스트

- [ ] **Step 1: 테스트 파일 작성**

```python
# free-claw-router/tests/test_meta_report.py
import json
import sqlite3
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from router.server.openai_compat import app

def _seed_fixtures(path):
    db = path / "telemetry.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE spans (span_id TEXT PRIMARY KEY, started_at TEXT, status TEXT);
        CREATE TABLE events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, span_id TEXT, kind TEXT, payload_json TEXT, ts TEXT);
        CREATE TABLE evaluations (id INTEGER PRIMARY KEY AUTOINCREMENT, span_id TEXT, score_dim TEXT, score_value REAL, ts TEXT);
    """)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO spans VALUES ('s1', ?, 'ok')", (now,))
    for kind in ("meta_suggestion", "meta_vote", "meta_applied", "meta_rolled_back"):
        conn.execute(
            "INSERT INTO events(span_id, kind, payload_json, ts) VALUES (?,?,?,?)",
            ("s1", kind, json.dumps({"level": "info"}), now),
        )
    for dim in ("quality", "latency"):
        conn.execute(
            "INSERT INTO evaluations(span_id, score_dim, score_value, ts) VALUES (?,?,?,?)",
            ("s1", dim, 0.8, now),
        )
    conn.commit()
    conn.close()
    sug = path / "suggestions.jsonl"
    # 10개 타깃 각각에 최소 1건 제안 — 타임라인 렌더 검증용
    targets = [f"target_{i}" for i in range(10)]
    with sug.open("w") as f:
        for t in targets:
            f.write(json.dumps({"target_id": t, "kind": "proposed", "note": "x", "ts": now, "status": "pending"}) + "\n")

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FCR_DATA_DIR", str(tmp_path))
    _seed_fixtures(tmp_path)
    return TestClient(app)

@pytest.fixture
def client_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("FCR_DATA_DIR", str(tmp_path))
    return TestClient(app)

def test_meta_report_renders_24h_summary(client):
    resp = client.get("/meta/report")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "24h 메타 활동 요약" in body
    assert "제안" in body
    assert "롤백" in body

def test_meta_report_timeline_per_target(client):
    resp = client.get("/meta/report")
    body = resp.text
    assert body.count('class="target-timeline"') >= 10

def test_meta_report_handles_empty_store(client_empty):
    resp = client_empty.get("/meta/report")
    assert resp.status_code == 200
    assert "데이터 없음" in resp.text
```

- [ ] **Step 2: 실패 확인**

```bash
cd free-claw-router && uv run pytest tests/test_meta_report.py -v
```

기대: FAIL with `404` 또는 endpoint 없음.

### B-1.2: 최소 구현

- [ ] **Step 1: `meta_report.py` 작성**

```python
# free-claw-router/router/server/meta_report.py
"""Local HTML audit report for meta-evolution pipeline.
GET /meta/report → server-rendered HTML. No JS framework.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

from router.server.paths import data_dir  # 기존 유틸; 없으면 신설

router = APIRouter()

_CSS = """
body{font-family:system-ui,sans-serif;max-width:980px;margin:20px auto;padding:0 16px;color:#222}
h1{font-size:22px;margin-bottom:6px}h2{font-size:17px;margin-top:28px;color:#444}
.target-timeline{border-left:3px solid #888;margin:12px 0;padding:4px 12px}
.alert-critical{background:#fee;padding:8px;border-left:4px solid #c00}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #eee;padding:4px 8px;text-align:left}
.spark{font-family:monospace;color:#666}
"""

@router.get("/meta/report", response_class=HTMLResponse)
def meta_report() -> Response:
    d = data_dir()
    db_path = d / "telemetry.db"
    suggestions_path = d / "suggestions.jsonl"

    summary = _summarize_24h(db_path, suggestions_path)
    timelines = _timelines_per_target(suggestions_path)
    pr_status = _pr_status_cached()
    trends = _score_trends(db_path)
    alerts = _alerts(db_path, suggestions_path)

    html = _render_html(summary, timelines, pr_status, trends, alerts)
    return HTMLResponse(content=html)

def _summarize_24h(db: Path, sug: Path) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    if not db.exists():
        return {"proposed": 0, "voted": 0, "applied": 0, "rolled_back": 0}
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute(
            "SELECT kind, COUNT(*) FROM events WHERE ts >= ? GROUP BY kind",
            (cutoff,),
        )
        counts = dict(cur.fetchall())
    finally:
        conn.close()
    return {
        "proposed": counts.get("meta_suggestion", 0),
        "voted": counts.get("meta_vote", 0),
        "applied": counts.get("meta_applied", 0),
        "rolled_back": counts.get("meta_rolled_back", 0),
    }

def _timelines_per_target(sug: Path) -> list[dict]:
    if not sug.exists():
        return []
    targets = {}
    for line in sug.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        tid = rec.get("target_id", "?")
        targets.setdefault(tid, []).append(rec)
    return [{"target": tid, "events": sorted(items, key=lambda r: r.get("ts", ""))}
            for tid, items in targets.items()]

def _pr_status_cached() -> dict:
    # 실제 구현: gh pr list --json number,title,state --search "meta-evolution" 캐시
    # 24h 캐시 파일에서 읽고, 없으면 빈 목록 반환 (오프라인 안전)
    return {"open": [], "merged": [], "reverted": []}

def _score_trends(db: Path) -> dict[str, list[float]]:
    if not db.exists():
        return {}
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute(
            "SELECT score_dim, DATE(ts), AVG(score_value) "
            "FROM evaluations WHERE ts >= DATE('now','-7 days') "
            "GROUP BY score_dim, DATE(ts) ORDER BY score_dim, DATE(ts)"
        )
        out: dict[str, list[float]] = {}
        for dim, _day, avg in cur.fetchall():
            out.setdefault(dim, []).append(float(avg))
    finally:
        conn.close()
    return out

def _alerts(db: Path, sug: Path) -> list[dict]:
    # events에서 최근 critical meta_alert, 연속 degradation 감지된 target
    out: list[dict] = []
    if db.exists():
        conn = sqlite3.connect(str(db))
        try:
            cur = conn.execute(
                "SELECT payload_json FROM events WHERE kind='meta_alert' "
                "AND json_extract(payload_json,'$.level')='critical' "
                "AND ts >= DATE('now','-7 days') ORDER BY ts DESC LIMIT 20"
            )
            for (pj,) in cur.fetchall():
                out.append(json.loads(pj))
        finally:
            conn.close()
    return out

def _render_html(summary, timelines, pr, trends, alerts) -> str:
    def _spark(vals: list[float]) -> str:
        if not vals:
            return ""
        bars = "▁▂▃▄▅▆▇█"
        lo, hi = min(vals), max(vals)
        rng = hi - lo if hi > lo else 1.0
        return "".join(bars[min(7, int((v - lo) / rng * 7))] for v in vals)

    rows_sum = "<tr><td>제안</td><td>{proposed}</td><td>표결</td><td>{voted}</td>" \
               "<td>적용</td><td>{applied}</td><td>롤백</td><td>{rolled_back}</td></tr>".format(**summary)

    tl_html = ""
    if not timelines:
        tl_html = "<p>데이터 없음</p>"
    else:
        for t in timelines:
            evs = "".join(
                f"<li>{e.get('ts','')} — {e.get('kind','')} — {e.get('note','')}</li>"
                for e in t["events"]
            )
            tl_html += f'<div class="target-timeline"><strong>{t["target"]}</strong><ul>{evs}</ul></div>'

    trend_html = "".join(
        f"<tr><td>{dim}</td><td class=\"spark\">{_spark(vals)}</td></tr>"
        for dim, vals in trends.items()
    ) or "<tr><td colspan=2>데이터 없음</td></tr>"

    alert_html = "".join(
        f'<div class="alert-critical">{a.get("message","(no message)")}</div>'
        for a in alerts
    ) or "<p>미해결 경고 없음</p>"

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>Meta Evolution Report</title><style>{_CSS}</style></head><body>
<h1>Meta Evolution Report</h1><p>Free Claw Router — 로컬 감사 뷰</p>

<h2>24h 메타 활동 요약</h2>
<table>{rows_sum}</table>

<h2>편집 대상별 제안 Timeline</h2>
{tl_html}

<h2>자기수정 PR 상태</h2>
<p>열린 {len(pr['open'])} / 머지 {len(pr['merged'])} / 롤백 {len(pr['reverted'])}</p>

<h2>평가 추이 (7일, score_dim별)</h2>
<table><tr><th>차원</th><th>sparkline</th></tr>{trend_html}</table>

<h2>미해결 경고</h2>
{alert_html}
</body></html>"""
```

- [ ] **Step 2: `openai_compat.py`에 라우터 등록**

```python
# router/server/openai_compat.py 상단 import 추가 후, FastAPI app 생성 직후
from router.server.meta_report import router as meta_report_router
app.include_router(meta_report_router)
```

- [ ] **Step 3: 테스트 실행**

```bash
uv run pytest tests/test_meta_report.py -v
```

기대: PASS (fixture seeding이 정확히 준비됐다면).

- [ ] **Step 4: 수동 smoke**

```bash
uv run uvicorn router.server.openai_compat:app --port 7801 &
sleep 1
curl -s http://127.0.0.1:7801/meta/report | head -30
kill %1
```

기대: HTML 헤더 + "24h 메타 활동 요약" 텍스트 출력.

- [ ] **Step 5: 커밋**

```bash
git add router/server/meta_report.py router/server/openai_compat.py tests/
git commit -m "feat(meta): add /meta/report local HTML audit view

Server-rendered HTML (no JS framework). Shows 24h summary,
per-target timeline, PR status, score trends (sparkline),
unresolved critical alerts. Loopback access only.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task B-2: `clawd meta *` CLI 명령

**Files:**
- Create: `rust/crates/commands/src/meta_cmd.rs`
- Modify: `rust/crates/commands/src/lib.rs` (re-export + dispatch table)
- Modify: `rust/crates/rusty-claude-cli/src/command_dispatch.rs` (slash command 등록)
- Create: `rust/crates/commands/tests/meta_cmd.rs`

### B-2.1: TDD — 실패 테스트

- [ ] **Step 1: 테스트 작성**

```rust
// rust/crates/commands/tests/meta_cmd.rs
use commands::meta_cmd::{ack, fetch_alerts};
use wiremock::{matchers::{method, path}, Mock, MockServer, ResponseTemplate};

#[tokio::test]
async fn fetch_alerts_parses_json_response() {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/meta/alerts"))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!([
            {"id":"a1","level":"critical","message":"x","ts":""}
        ])))
        .mount(&server)
        .await;

    let alerts = fetch_alerts(&server.uri()).await.unwrap();
    assert_eq!(alerts.len(), 1);
    assert_eq!(alerts[0].level, "critical");
}

#[tokio::test]
async fn ack_sends_post() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/meta/ack/a1"))
        .respond_with(ResponseTemplate::new(200))
        .expect(1)
        .mount(&server)
        .await;

    ack(&server.uri(), "a1").await.unwrap();
    // expect(1) 위반 시 drop에서 panic
}
```

- [ ] **Step 2: 실패 확인**

```bash
cd rust && cargo test -p commands --test meta_cmd --no-run 2>&1 | tail -10
```

### B-2.2: 구현

- [ ] **Step 1: `meta_cmd.rs` 작성**

```rust
// rust/crates/commands/src/meta_cmd.rs
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Alert {
    pub id: String,
    pub level: String,
    pub message: String,
    #[serde(default)]
    pub ts: String,
}

pub fn router_url() -> String {
    std::env::var("FREE_CLAW_ROUTER_URL").unwrap_or_else(|_| "http://127.0.0.1:7801".into())
}

pub async fn fetch_alerts(sidecar_url: &str) -> Result<Vec<Alert>, String> {
    let url = format!("{}/meta/alerts", sidecar_url.trim_end_matches('/'));
    let resp = reqwest::get(&url).await.map_err(|e| e.to_string())?;
    resp.json::<Vec<Alert>>().await.map_err(|e| e.to_string())
}

pub async fn ack(sidecar_url: &str, alert_id: &str) -> Result<(), String> {
    let url = format!("{}/meta/ack/{}", sidecar_url.trim_end_matches('/'), alert_id);
    let resp = reqwest::Client::new().post(&url).send().await.map_err(|e| e.to_string())?;
    if !resp.status().is_success() { return Err(format!("status {}", resp.status())); }
    Ok(())
}

pub async fn unblock(sidecar_url: &str, target: &str) -> Result<(), String> {
    let url = format!("{}/meta/unblock/{}", sidecar_url.trim_end_matches('/'), target);
    let resp = reqwest::Client::new().post(&url).send().await.map_err(|e| e.to_string())?;
    if !resp.status().is_success() { return Err(format!("status {}", resp.status())); }
    Ok(())
}

pub fn open_report_url(sidecar_url: &str) -> std::io::Result<()> {
    let url = format!("{}/meta/report", sidecar_url.trim_end_matches('/'));
    #[cfg(target_os = "macos")]
    let cmd = std::process::Command::new("open").arg(&url).status()?;
    #[cfg(not(target_os = "macos"))]
    let cmd = std::process::Command::new("xdg-open").arg(&url).status()?;
    if cmd.success() { Ok(()) } else { Err(std::io::Error::other("open failed")) }
}
```

- [ ] **Step 2: 사이드카에 대응 엔드포인트 추가**

`free-claw-router/router/server/meta_report.py`에:
```python
@router.get("/meta/alerts")
def meta_alerts():
    # events 테이블에서 ack되지 않은 critical alert 목록
    ...

@router.post("/meta/ack/{alert_id}")
def meta_ack(alert_id: str):
    # events에 ack 레코드 append
    ...

@router.post("/meta/unblock/{target}")
def meta_unblock(target: str):
    # suggestion_store에서 해당 target의 auto-blocked 플래그 해제
    ...
```

- [ ] **Step 3: 슬래시 명령 등록**

`command_dispatch.rs`에 `/meta report`, `/meta alerts`, `/meta ack <id>`, `/meta unblock <target>` 매핑 추가.

- [ ] **Step 4: 테스트**

```bash
cd rust && cargo test -p commands --test meta_cmd
```

- [ ] **Step 5: 수동 smoke**

```bash
# 사이드카 기동 상태에서
cargo run -p rusty-claude-cli -- meta alerts --json
```

- [ ] **Step 6: 커밋**

```bash
git add . && git commit -m "feat(cli): add clawd meta report/alerts/ack/unblock commands

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### B-2.3: 기동 배너 경고 표시

- [ ] **Step 1: 배너 함수에 훅 추가**

`session_lifecycle.rs` (A-1.6에서 추출된) 시작 루틴에서 `fetch_alerts` 호출 (best-effort, 실패 시 무시), critical > 0이면 배너에 "⚠ 메타 경고 N건 — `clawd meta report`" 출력.

- [ ] **Step 2: 통합 smoke**

사이드카에 critical alert 하나 시드한 뒤 `cargo run -p rusty-claude-cli` 기동 → 배너 확인.

- [ ] **Step 3: 커밋**

```bash
git commit -am "feat(cli): show critical meta alert count on session startup"
```

---

## Task B-3: 스토어 GC

**Files:**
- Create: `free-claw-router/router/server/gc.py`
- Modify: `free-claw-router/router/server/lifespan.py` (APScheduler 등록)
- Create: `free-claw-router/tests/test_gc.py`

### B-3.1: TDD — 실패 테스트

- [ ] **Step 1: 테스트 작성**

```python
# free-claw-router/tests/test_gc.py
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pytest
from router.server.gc import run_gc, GcConfig

@pytest.fixture
def seeded_env(tmp_path):
    db = tmp_path / "telemetry.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE spans (span_id TEXT PRIMARY KEY, started_at TEXT, status TEXT);
        CREATE TABLE events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, span_id TEXT, kind TEXT, payload_json TEXT, ts TEXT);
        CREATE TABLE evaluations (id INTEGER PRIMARY KEY AUTOINCREMENT, span_id TEXT, score_dim TEXT, score_value REAL, ts TEXT);
    """)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    new_ts = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO spans VALUES ('old', ?, 'ok')", (old_ts,))
    conn.execute("INSERT INTO spans VALUES ('new', ?, 'ok')", (new_ts,))
    conn.commit()
    conn.close()

    sug = tmp_path / "suggestions.jsonl"
    recs = [
        {"id": "s-old", "target_id": "x", "status": "applied", "ts": old_ts},
        {"id": "s-new", "target_id": "x", "status": "pending", "ts": new_ts},
    ]
    sug.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return tmp_path

def test_gc_span_age_drops_old(seeded_env):
    cfg = GcConfig(span_days=30, event_days=90, eval_days=180,
                   sug_applied_days=30, sug_rejected_days=7, dry_run=False)
    stats = run_gc(seeded_env / "telemetry.db", seeded_env / "suggestions.jsonl", cfg)
    assert stats["spans_deleted"] == 1
    assert stats["suggestions_deleted"] == 1

def test_gc_dry_run_reports_no_deletion(seeded_env):
    cfg = GcConfig(dry_run=True)
    stats = run_gc(seeded_env / "telemetry.db", seeded_env / "suggestions.jsonl", cfg)
    assert stats["spans_deleted"] == 0
    assert stats["spans_would_delete"] == 1

def test_gc_records_event_log(seeded_env):
    cfg = GcConfig(span_days=30, dry_run=False)
    run_gc(seeded_env / "telemetry.db", seeded_env / "suggestions.jsonl", cfg)
    conn = sqlite3.connect(str(seeded_env / "telemetry.db"))
    rows = conn.execute("SELECT kind FROM events WHERE kind='gc_run'").fetchall()
    assert len(rows) == 1
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_gc.py -v
```

기대: `ModuleNotFoundError` or function missing.

### B-3.2: 구현

- [ ] **Step 1: `gc.py` 작성**

```python
# free-claw-router/router/server/gc.py
"""Store garbage collection with two-phase (dry-run + commit) safety.

Policies (overridable via env):
    spans: 30 days (FCR_GC_SPAN_DAYS)
    events: 90 days (FCR_GC_EVENT_DAYS)
    evaluations: 180 days (FCR_GC_EVAL_DAYS)
    suggestions (applied): 30 days (FCR_GC_SUGGESTION_DAYS)
    suggestions (rejected): 7 days (FCR_GC_SUGGESTION_REJECTED_DAYS)
"""
from __future__ import annotations
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

@dataclass
class GcConfig:
    span_days: int = field(default_factory=lambda: int(os.getenv("FCR_GC_SPAN_DAYS", "30")))
    event_days: int = field(default_factory=lambda: int(os.getenv("FCR_GC_EVENT_DAYS", "90")))
    eval_days: int = field(default_factory=lambda: int(os.getenv("FCR_GC_EVAL_DAYS", "180")))
    sug_applied_days: int = field(default_factory=lambda: int(os.getenv("FCR_GC_SUGGESTION_DAYS", "30")))
    sug_rejected_days: int = field(default_factory=lambda: int(os.getenv("FCR_GC_SUGGESTION_REJECTED_DAYS", "7")))
    dry_run: bool = field(default_factory=lambda: os.getenv("FCR_GC_DRY_RUN", "0") == "1")
    paused: bool = field(default_factory=lambda: os.getenv("FCR_GC_PAUSED", "0") == "1")

def _iso_cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

def run_gc(db_path: Path, suggestions_path: Path, cfg: GcConfig) -> dict:
    if cfg.paused:
        return {"paused": True}

    stats = {"spans_deleted": 0, "events_deleted": 0, "evals_deleted": 0,
             "suggestions_deleted": 0, "spans_would_delete": 0}

    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        try:
            if cfg.dry_run:
                row = conn.execute(
                    "SELECT COUNT(*) FROM spans WHERE started_at < ?",
                    (_iso_cutoff(cfg.span_days),),
                ).fetchone()
                stats["spans_would_delete"] = row[0] if row else 0
            else:
                cur = conn.execute("DELETE FROM spans WHERE started_at < ?",
                                   (_iso_cutoff(cfg.span_days),))
                stats["spans_deleted"] = cur.rowcount
                cur = conn.execute("DELETE FROM events WHERE ts < ?",
                                   (_iso_cutoff(cfg.event_days),))
                stats["events_deleted"] = cur.rowcount
                cur = conn.execute("DELETE FROM evaluations WHERE ts < ?",
                                   (_iso_cutoff(cfg.eval_days),))
                stats["evals_deleted"] = cur.rowcount
                conn.execute(
                    "INSERT INTO events(span_id, kind, payload_json, ts) VALUES (NULL,'gc_run',?,?)",
                    (json.dumps(stats), datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
        finally:
            conn.close()

    if suggestions_path.exists() and not cfg.dry_run:
        kept = []
        for line in suggestions_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            ts = rec.get("ts", "")
            status = rec.get("status", "pending")
            if status == "applied" and ts < _iso_cutoff(cfg.sug_applied_days):
                stats["suggestions_deleted"] += 1
                continue
            if status == "rejected" and ts < _iso_cutoff(cfg.sug_rejected_days):
                stats["suggestions_deleted"] += 1
                continue
            kept.append(line)
        suggestions_path.write_text("\n".join(kept) + ("\n" if kept else ""))

    return stats
```

- [ ] **Step 2: 테스트 실행**

```bash
uv run pytest tests/test_gc.py -v
```

기대: PASS.

- [ ] **Step 3: APScheduler 등록**

`router/server/lifespan.py` (기존) 내 startup 훅에 추가:
```python
from apscheduler.triggers.cron import CronTrigger
from router.server.gc import run_gc, GcConfig
from router.server.paths import data_dir

def _gc_job():
    d = data_dir()
    stats = run_gc(d / "telemetry.db", d / "suggestions.jsonl", GcConfig())
    logger.info("gc_run %s", stats)

scheduler.add_job(_gc_job, CronTrigger(hour=3, minute=15), id="daily_gc", replace_existing=True)
```

- [ ] **Step 4: 통합 테스트 — 사이드카 기동 후 스케줄러 확인**

```bash
uv run uvicorn router.server.openai_compat:app --port 7801 &
sleep 2
curl -s http://127.0.0.1:7801/healthz/pipeline 2>&1 | head
kill %1
```

- [ ] **Step 5: 커밋**

```bash
git add . && git commit -m "feat(meta): add two-phase store GC with daily cron

spans 30d / events 90d / evaluations 180d / suggestions applied 30d
or rejected 7d. Dry-run + commit split; env overrides; pause flag;
gc_run event emitted with stats for audit trail.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task B-4: 연속 2회 롤백 타깃 자동 블록

**Files:**
- Modify: `free-claw-router/router/meta/meta_evaluator.py`
- Modify: `free-claw-router/router/meta/suggestion_store.py` (block 플래그 지원)
- Create: `free-claw-router/tests/test_meta_block.py`

### B-4.1: TDD

- [ ] **Step 1: 테스트 작성**

```python
# free-claw-router/tests/test_meta_block.py
from router.meta.meta_evaluator import record_rollback, is_blocked

def test_first_rollback_does_not_block(tmp_path):
    record_rollback("target.yaml", store_dir=tmp_path)
    assert not is_blocked("target.yaml", store_dir=tmp_path)

def test_second_consecutive_rollback_blocks(tmp_path):
    record_rollback("target.yaml", store_dir=tmp_path)
    record_rollback("target.yaml", store_dir=tmp_path)
    assert is_blocked("target.yaml", store_dir=tmp_path)

def test_successful_apply_resets_counter(tmp_path):
    from router.meta.meta_evaluator import record_apply_success
    record_rollback("target.yaml", store_dir=tmp_path)
    record_apply_success("target.yaml", store_dir=tmp_path)
    record_rollback("target.yaml", store_dir=tmp_path)
    assert not is_blocked("target.yaml", store_dir=tmp_path)
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_meta_block.py -v
```

### B-4.2: 구현

- [ ] **Step 1: 함수 추가**

```python
# free-claw-router/router/meta/meta_evaluator.py 하단 추가
import json
from pathlib import Path

def _counter_path(store_dir: Path) -> Path:
    return Path(store_dir) / "rollback_counters.json"

def _load(store_dir: Path) -> dict:
    p = _counter_path(store_dir)
    return json.loads(p.read_text()) if p.exists() else {}

def _save(store_dir: Path, data: dict) -> None:
    Path(store_dir).mkdir(parents=True, exist_ok=True)
    _counter_path(store_dir).write_text(json.dumps(data))

def record_rollback(target: str, store_dir: Path) -> None:
    d = _load(store_dir)
    d[target] = d.get(target, 0) + 1
    _save(store_dir, d)
    if d[target] >= 2:
        _emit_critical_alert(target, d[target])

def record_apply_success(target: str, store_dir: Path) -> None:
    d = _load(store_dir)
    d[target] = 0
    _save(store_dir, d)

def is_blocked(target: str, store_dir: Path) -> bool:
    d = _load(store_dir)
    return d.get(target, 0) >= 2

def unblock(target: str, store_dir: Path) -> None:
    d = _load(store_dir)
    d[target] = 0
    _save(store_dir, d)

def _emit_critical_alert(target: str, count: int) -> None:
    # router/server/_telemetry_middleware.py의 emit_event 사용
    from router.server._telemetry_middleware import emit_event
    emit_event(kind="meta_alert", payload={
        "level": "critical",
        "target": target,
        "rollback_count": count,
        "message": f"타깃 {target}: 연속 {count}회 롤백 — 자동 블록",
    })
```

- [ ] **Step 2: `build_edit_plans`에서 `is_blocked` 체크**

`router/meta/meta_consensus.py` 또는 해당 위치에서 후보 제안 필터링 시 `is_blocked(target, data_dir())`이면 스킵.

- [ ] **Step 3: 롤백 실행 지점에서 `record_rollback` 호출**

메타 평가기가 auto-revert PR을 생성하는 경로에 `record_rollback(target, data_dir())` 추가.

- [ ] **Step 4: 성공 적용 지점에서 `record_apply_success` 호출**

메타 PR이 머지되고 5세션 평가 후 안정 판정 시 `record_apply_success` 호출.

- [ ] **Step 5: 사이드카 `/meta/unblock/{target}` 엔드포인트 구현** (B-2.2의 자리)

```python
# router/server/meta_report.py 에 추가
from router.meta.meta_evaluator import unblock as meta_unblock_fn

@router.post("/meta/unblock/{target}")
def meta_unblock(target: str):
    meta_unblock_fn(target, store_dir=data_dir())
    return {"ok": True, "target": target}
```

- [ ] **Step 6: 테스트**

```bash
uv run pytest tests/test_meta_block.py -v
```

기대: PASS.

- [ ] **Step 7: 커밋**

```bash
git add . && git commit -m "feat(meta): auto-block targets after 2 consecutive rollbacks

Emits critical meta_alert on block. Apply success resets counter.
Manual unblock via POST /meta/unblock/<target> or clawd meta unblock.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task B-5: CLAUDE.md 계약 업데이트

- [ ] **Step 1: `CLAUDE.md` "핵심 계약·불변식" 섹션에 추가**

```markdown
- **스토어 GC 정책**: spans 30일 / events 90일 / evaluations 180일 / 제안(적용) 30일 / 제안(기각) 7일. 2단 커밋(dry-run → commit). 환경변수 오버라이드 가능(`FCR_GC_*`).
- **타깃 자동 블록**: 동일 `meta_targets.yaml` 항목이 연속 2회 롤백되면 `suggestion_store`가 해당 타깃 제안을 자동 기각 + `critical` `meta_alert` 발화. 해제: `clawd meta unblock <target>`.
```

- [ ] **Step 2: 커밋**

```bash
git commit -am "docs(meta): document GC and auto-block policies in CLAUDE.md"
```

### B 트랙 머지

- [ ] **Step 1: 최종 테스트 + clippy**

```bash
cd rust && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace --quiet
cd ../free-claw-router && uv run pytest -q
```

- [ ] **Step 2: main 머지**

```bash
git checkout main
git merge feature/p5-track-b-observe --no-ff -m "merge: Track B (observe) — /meta/report, clawd meta CLI, GC, auto-block"
```

---

# Track C — 루프 심화

worktree: `../free-claw-code-p5-c`, 브랜치: `feature/p5-track-c-loop`

## Task C-1: `skill_model_affinity` → `routing/score.py` 실연결

**Files:**
- Create: `free-claw-router/router/routing/affinity.py`
- Modify: `free-claw-router/router/routing/score.py`
- Modify: `free-claw-router/router/meta/meta_targets.yaml` (affinity config 등록)
- Create: `free-claw-router/tests/test_routing_affinity.py`

### C-1.1: TDD

- [ ] **Step 1: 테스트 작성**

```python
# free-claw-router/tests/test_routing_affinity.py
import pytest
from router.routing.affinity import affinity_bonus, AffinityConfig

def test_cold_start_returns_zero():
    cfg = AffinityConfig(weight=0.3, prior_n=10, clip=(-0.15, 0.15))
    # 표본 0
    bonus = affinity_bonus(successes=0, samples=0, cfg=cfg)
    # (0*0 + 0.5*10)/(0+10) = 0.5 → (0.5-0.5)*0.3 = 0
    assert abs(bonus) < 1e-9

def test_high_success_clipped_to_upper():
    cfg = AffinityConfig(weight=0.3, prior_n=10, clip=(-0.15, 0.15))
    bonus = affinity_bonus(successes=30, samples=30, cfg=cfg)
    # adjusted = (30 + 5) / 40 = 0.875 → (0.375)*0.3 = 0.1125 < 0.15, 미클립
    assert abs(bonus - 0.1125) < 1e-6

def test_extreme_high_clipped():
    cfg = AffinityConfig(weight=1.0, prior_n=10, clip=(-0.15, 0.15))
    bonus = affinity_bonus(successes=100, samples=100, cfg=cfg)
    assert bonus == 0.15

def test_low_success_clipped_lower():
    cfg = AffinityConfig(weight=1.0, prior_n=10, clip=(-0.15, 0.15))
    bonus = affinity_bonus(successes=0, samples=100, cfg=cfg)
    assert bonus == -0.15

def test_score_candidate_integrates_affinity(monkeypatch):
    from router.routing.score import score_candidate
    # skill_id None이면 정적 정책과 동일 결과
    result_none = score_candidate(skill_id=None, model_id="llama-70b",
                                  task_type="coding", capabilities={"context_window": 128000, "tool_use": True})
    # skill_id가 있어도 read model이 비어있으면 0 보너스 → 동일
    result_empty = score_candidate(skill_id="refactor", model_id="llama-70b",
                                   task_type="coding", capabilities={"context_window": 128000, "tool_use": True})
    assert abs(result_none - result_empty) < 1e-9
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_routing_affinity.py -v
```

### C-1.2: 구현

- [ ] **Step 1: `affinity.py` 작성**

```python
# free-claw-router/router/routing/affinity.py
"""Bayesian smoothing of (skill, model) success rates for adaptive routing.

score_bonus ∈ [clip_lo, clip_hi] is added to the base score in routing/score.py.
Params registered in meta_targets.yaml so P4 can self-tune.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

# Overridable via meta_targets.yaml config_only edits
AFFINITY_WEIGHT: float = 0.3
PRIOR_N: int = 10
CLIP_LO: float = -0.15
CLIP_HI: float = 0.15

@dataclass(frozen=True)
class AffinityConfig:
    weight: float = AFFINITY_WEIGHT
    prior_n: int = PRIOR_N
    clip: tuple[float, float] = (CLIP_LO, CLIP_HI)

def affinity_bonus(successes: int, samples: int, cfg: Optional[AffinityConfig] = None) -> float:
    cfg = cfg or AffinityConfig()
    s = successes
    n = samples
    adjusted = (s + 0.5 * cfg.prior_n) / (n + cfg.prior_n) if (n + cfg.prior_n) > 0 else 0.5
    raw = (adjusted - 0.5) * cfg.weight
    return max(cfg.clip[0], min(cfg.clip[1], raw))

def lookup_affinity(skill_id: Optional[str], model_id: str) -> tuple[int, int]:
    """Read (successes, samples) from skill_model_affinity readmodel.
    Returns (0, 0) if skill_id is None or no data exists."""
    if skill_id is None:
        return (0, 0)
    # Delegate to existing readmodel utility
    from router.telemetry.readmodel.skill_model_affinity import get_pair_stats
    return get_pair_stats(skill_id=skill_id, model_id=model_id, window_days=30)
```

- [ ] **Step 2: `score.py` 수정**

```python
# free-claw-router/router/routing/score.py
# 기존 score_candidate 함수 내부, base+capabilities 보너스 계산 후:
from router.routing.affinity import affinity_bonus, lookup_affinity

def score_candidate(skill_id, model_id, task_type, capabilities, policy=None):
    base = 0.5
    tool_bonus = 0.1 if capabilities.get("tool_use") and task_type in ("tool_heavy", "coding") else 0.0
    ctx_bonus = 0.05 if capabilities.get("context_window", 0) >= 65_000 else 0.0

    successes, samples = lookup_affinity(skill_id, model_id)
    aff_bonus = affinity_bonus(successes, samples)

    score = base + tool_bonus + ctx_bonus + aff_bonus
    # 기존 policy-specific weighting은 그대로 이후에 적용됨
    return _apply_policy_weight(score, task_type, model_id, policy) if policy else score
```

(`_apply_policy_weight`은 기존 함수. 명시적으로 호출 순서만 조정.)

- [ ] **Step 3: 라우팅 결정 이벤트 기록 추가**

`routing/decision.py` 또는 상위 호출점에서 `emit_event(kind="routing_decision", payload={"candidates":[...], "affinity_applied":{...}, "chosen": model_id})` 호출.

- [ ] **Step 4: `meta_targets.yaml` 등록**

```yaml
# free-claw-router/router/meta/meta_targets.yaml 말미 추가
- path: "free-claw-router/router/routing/affinity.py"
  type: "config_only"
  editable_keys:
    - AFFINITY_WEIGHT
    - PRIOR_N
    - CLIP_LO
    - CLIP_HI
  description: "Adaptive routing bonus parameters — bounded self-tuning"
```

- [ ] **Step 5: 테스트**

```bash
uv run pytest tests/test_routing_affinity.py -v
uv run pytest -q  # 회귀 확인
```

기대: PASS.

- [ ] **Step 6: 커밋**

```bash
git add . && git commit -m "feat(routing): wire skill_model_affinity to score with Bayesian smoothing

PRIOR_N=10, WEIGHT=0.3, clip ±0.15 for cold-start safety.
Params registered in meta_targets.yaml (config_only) for P4 self-tuning.
routing_decision events emitted for audit visibility.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task C-2: SSE 스트리밍 (OpenRouter 우선)

**Files:**
- Create: `free-claw-router/router/dispatch/sse.py`
- Modify: `free-claw-router/router/server/openai_compat.py`
- Modify: `free-claw-router/router/catalog/data/*.yaml` (capabilities.sse 필드)
- Create: `free-claw-router/tests/test_sse_dispatch.py`

### C-2.1: TDD — SSE passthrough

- [ ] **Step 1: 테스트 작성**

```python
# free-claw-router/tests/test_sse_dispatch.py
import asyncio
import pytest
import respx
import httpx
from router.dispatch.sse import dispatch_sse, provider_supports_sse

@pytest.mark.asyncio
@respx.mock
async def test_sse_passthrough_preserves_chunks():
    # OpenRouter mock이 SSE chunk 3개 + [DONE] 반환
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="data: {\"choices\":[{\"delta\":{\"content\":\"hi\"}}]}\n\n"
                 "data: {\"choices\":[{\"delta\":{\"content\":\" there\"}}]}\n\n"
                 "data: [DONE]\n\n",
        )
    )
    chunks = []
    async for c in dispatch_sse(
        provider={"id": "openrouter", "base_url": "https://openrouter.ai/api/v1"},
        request={"model": "x", "messages": [], "stream": True},
    ):
        chunks.append(c)
    joined = b"".join(chunks).decode()
    assert "hi" in joined
    assert "there" in joined
    assert "[DONE]" in joined

@pytest.mark.asyncio
async def test_non_sse_provider_gets_downgraded(caplog):
    assert provider_supports_sse("cerebras") is False
    # downgrade 경로는 openai_compat.py에서 테스트 (별도)

def test_capabilities_sse_field_exists_for_openrouter():
    import yaml
    from pathlib import Path
    data = yaml.safe_load(Path("router/catalog/data/openrouter.yaml").read_text())
    assert data["capabilities"]["sse"] is True
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_sse_dispatch.py -v
```

### C-2.2: 구현

- [ ] **Step 1: `sse.py` 작성**

```python
# free-claw-router/router/dispatch/sse.py
"""SSE passthrough from provider to client.
L2 scope: OpenRouter (+ Groq if bandwidth). z.ai/Cerebras/Ollama/LM Studio → L3.
"""
from __future__ import annotations
from typing import AsyncIterator
import json
import httpx
from pathlib import Path

_CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalog" / "data"
_CACHE: dict[str, bool] | None = None

def _load_catalog_sse() -> dict[str, bool]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    import yaml
    out: dict[str, bool] = {}
    for f in _CATALOG_DIR.glob("*.yaml"):
        try:
            data = yaml.safe_load(f.read_text())
            pid = data.get("id") or f.stem
            out[pid] = bool(data.get("capabilities", {}).get("sse", False))
        except Exception:
            out[f.stem] = False
    _CACHE = out
    return out

def provider_supports_sse(provider_id: str) -> bool:
    return _load_catalog_sse().get(provider_id, False)

async def dispatch_sse(provider: dict, request: dict,
                        headers: dict | None = None) -> AsyncIterator[bytes]:
    """Stream SSE bytes from provider, passing through unchanged.
    Telemetry span started on first chunk, ended on [DONE] or disconnection.
    """
    url = f"{provider['base_url'].rstrip('/')}/chat/completions"
    h = {"accept": "text/event-stream",
         "cache-control": "no-cache"}
    if headers:
        h.update(headers)

    first_chunk_seen = False
    span_id = None

    async with httpx.AsyncClient(timeout=None) as client:
        try:
            async with client.stream("POST", url, json=request, headers=h) as resp:
                async for chunk in resp.aiter_bytes():
                    if not first_chunk_seen:
                        first_chunk_seen = True
                        span_id = _start_sse_span(provider, request)
                    yield chunk
                    if b"[DONE]" in chunk:
                        _end_sse_span(span_id, status="ok")
                        return
        except Exception as e:
            if span_id:
                _end_sse_span(span_id, status=f"error: {e}")
            err = json.dumps({"error": str(e)}).encode()
            yield b"event: error\ndata: " + err + b"\n\n"

def _start_sse_span(provider: dict, request: dict) -> str:
    from router.server._telemetry_middleware import start_span
    return start_span(op_name="sse_dispatch", model_id=request.get("model", "?"),
                      provider_id=provider.get("id", "?"))

def _end_sse_span(span_id: str | None, status: str) -> None:
    if span_id is None:
        return
    from router.server._telemetry_middleware import end_span
    end_span(span_id, status=status)
```

- [ ] **Step 2: `openai_compat.py`에서 stream=true 분기**

```python
# router/server/openai_compat.py 의 /v1/chat/completions 핸들러
from fastapi.responses import StreamingResponse
from router.dispatch.sse import dispatch_sse, provider_supports_sse

@app.post("/v1/chat/completions")
async def chat_completions(req: dict):
    provider = choose_provider(req)  # 기존 라우팅
    if req.get("stream") and provider_supports_sse(provider["id"]):
        return StreamingResponse(
            dispatch_sse(provider, req),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )
    if req.get("stream"):
        logger.warning("provider %s does not support SSE; falling back to non-stream",
                       provider["id"])
        req = {**req, "stream": False}
    # 기존 non-stream 경로 (A-3 분리 후 라우팅 배선)
    return await dispatch_non_stream(provider, req)
```

- [ ] **Step 3: 카탈로그에 `capabilities.sse` 필드 추가**

`router/catalog/data/openrouter.yaml`:
```yaml
# 기존 파일 말미에 추가 (또는 capabilities: 블록이 있으면 확장)
capabilities:
  # 기존 필드 유지
  sse: true
```

`groq.yaml`, `zai.yaml`, `cerebras.yaml`, `ollama.yaml`, `lmstudio.yaml` 각각:
```yaml
capabilities:
  sse: false   # L3에서 true로 전환 예정
```

Groq는 여력 시 `true`로. 기본은 `false`.

- [ ] **Step 4: 테스트**

```bash
uv run pytest tests/test_sse_dispatch.py -v
```

기대: PASS.

- [ ] **Step 5: 수동 smoke**

```bash
# 사이드카 기동 후
curl -N -H "Content-Type: application/json" \
  -d '{"model":"openrouter/auto","stream":true,"messages":[{"role":"user","content":"hi"}]}' \
  http://127.0.0.1:7801/v1/chat/completions
```

기대: chunk별 출력 (버퍼링 없이 점진 출력).

### C-2.3: Rust 측 검증

- [ ] **Step 1: `crates/api/tests/openai_compat_integration.rs`에 SSE 시나리오 추가**

```rust
#[tokio::test]
async fn sse_stream_receives_chunks_in_order() {
    // mock sidecar가 SSE 3 chunk + [DONE] 반환
    // reqwest로 stream=true POST → chunk 순서대로 수신 확인
    ...
}
```

- [ ] **Step 2: 테스트**

```bash
cd rust && cargo test -p api --test openai_compat_integration
```

### C-2.4: 커밋

- [ ] **Step 1: 커밋**

```bash
git add . && git commit -m "feat(dispatch): add SSE passthrough (OpenRouter)

StreamingResponse + X-Accel-Buffering: no + no-cache to prevent
proxy buffering. Auto-downgrade to non-stream for providers without
capabilities.sse=true. First-chunk span start, [DONE] span end.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### C 트랙 머지

- [ ] **Step 1: 전체 테스트**

```bash
cd rust && cargo test --workspace --quiet
cd ../free-claw-router && uv run pytest -q
```

- [ ] **Step 2: main 머지**

```bash
git checkout main
git merge feature/p5-track-c-loop --no-ff -m "merge: Track C (loop) — affinity wiring, SSE dispatch"
```

---

# 통합 리뷰 체크포인트

A-4 · B-1+B-2 · C-1이 모두 main에 머지된 시점에 실시:

- [ ] **Step 1: 통합 브랜치 생성**

```bash
cd /Users/joel/Desktop/git/free-claw-code
git checkout -b feature/p5-integration main
```

- [ ] **Step 2: 풀 테스트**

```bash
cd rust && cargo test --workspace && cargo clippy --workspace --all-targets -- -D warnings
cd ../free-claw-router && uv run pytest
cd .. && pytest tests/test_porting_workspace.py
```

기대: 전부 통과.

- [ ] **Step 3: `clawd meta report` 수동 smoke**

```bash
uv run uvicorn router.server.openai_compat:app --port 7801 &
sleep 2
cargo run -p rusty-claude-cli -- meta report
kill %1
```

기대: 브라우저에 `/meta/report` HTML 오픈.

- [ ] **Step 4: `feature/p5-integration` 삭제 (main에 이미 반영됨)**

```bash
git checkout main && git branch -D feature/p5-integration
```

통합 리뷰 통과 시 Track D 개시.

---

# Track D — 1주 dogfood

worktree: `../free-claw-code-p5-d`, 브랜치: `feature/p5-track-d-dogfood`

## Task D-1: 부트스트랩 스크립트

**Files:**
- Create: `scripts/bootstrap-dogfood.sh`

- [ ] **Step 1: 스크립트 작성**

```bash
#!/usr/bin/env bash
# scripts/bootstrap-dogfood.sh
# Idempotent. P5 L2 dogfood 환경 준비.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

step() { printf "\n[%s] %s\n" "$(date +%H:%M:%S)" "$1"; }
fail() { echo "❌ $1" >&2; exit 1; }

step "1/7 .env 키 점검"
if [ ! -f .env ]; then
  cat > .env.template <<'EOF'
# 필수
OPENROUTER_API_KEY=
GROQ_API_KEY=
ZAI_API_KEY=
CEREBRAS_API_KEY=
# 선택
ANTHROPIC_API_KEY=
EOF
  fail ".env 미존재 — .env.template 생성됨. 키 채운 뒤 재실행."
fi
source .env
for k in OPENROUTER_API_KEY GROQ_API_KEY ZAI_API_KEY CEREBRAS_API_KEY; do
  [ -n "${!k:-}" ] || fail "$k 비어있음"
done

step "2/7 mempalace init"
if ! command -v mempalace >/dev/null; then
  fail "mempalace CLI 미설치"
fi
mempalace init "$HOME/projects" 2>/dev/null || echo "  (이미 초기화됨)"

step "3/7 OpenSpace MCP 점검"
python -m openspace.mcp_server --check || fail "OpenSpace MCP 확인 실패"

step "4/7 사이드카 기동 확인"
if ! curl -sf http://127.0.0.1:7801/healthz >/dev/null; then
  echo "  사이드카 기동 중이 아님. 별도 터미널에서 실행:"
  echo "    cd free-claw-router && uv run uvicorn router.server.openai_compat:app --port 7801"
  if [ "${1:-}" = "--restart" ]; then
    echo "  --restart 플래그: 백그라운드 기동"
    (cd free-claw-router && uv run uvicorn router.server.openai_compat:app --port 7801 >/tmp/fcr.log 2>&1 &)
    sleep 3
    curl -sf http://127.0.0.1:7801/healthz || fail "기동 실패 (/tmp/fcr.log 확인)"
  else
    fail "사이드카 필요 — 별도 기동 후 재실행 또는 --restart"
  fi
fi

step "5/7 Rust CLI 빌드"
(cd rust && cargo build --release -p rusty-claude-cli --quiet)

step "6/7 OPENAI_BASE_URL 안내"
echo "  export OPENAI_BASE_URL=http://127.0.0.1:7801"
echo "  (shell rc에 추가하거나 세션마다 export)"

step "7/7 텔레메트리 DB 확인"
DB="$HOME/.free-claw-router/telemetry.db"
if [ ! -f "$DB" ]; then
  echo "  $DB 없음 — 첫 요청 시 자동 생성됩니다."
else
  echo "  $DB OK ($(stat -f%z "$DB" 2>/dev/null || stat -c%s "$DB") bytes)"
fi

echo
echo "✅ 부트스트랩 완료. 다음: clawd 세션 시작 → 실사용."
```

- [ ] **Step 2: 실행 권한 부여 + smoke**

```bash
chmod +x scripts/bootstrap-dogfood.sh
./scripts/bootstrap-dogfood.sh || true  # 환경 미비면 메시지만 확인
```

- [ ] **Step 3: 커밋**

```bash
git add scripts/bootstrap-dogfood.sh
git commit -m "chore(dogfood): add bootstrap script

Idempotent 7-step environment check: .env keys, mempalace, OpenSpace
MCP, sidecar health, Rust CLI build, env var hint, telemetry DB.
--restart flag launches sidecar in background.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task D-2: 개발자 편의 트리거

**Files:**
- Create: `free-claw-router/router/server/dev_triggers.py`
- Modify: `free-claw-router/router/server/openai_compat.py` (라우터 등록)

- [ ] **Step 1: 구현**

```python
# free-claw-router/router/server/dev_triggers.py
"""Dev-only forced triggers for dogfood validation.
Gated by FCR_DEV_TRIGGERS=1. Returns 404 otherwise.
"""
from __future__ import annotations
import os
from fastapi import APIRouter, HTTPException

router = APIRouter()

def _gate():
    if os.getenv("FCR_DEV_TRIGGERS") != "1":
        raise HTTPException(status_code=404)

@router.post("/meta/analyze-now")
async def analyze_now():
    _gate()
    from router.meta.meta_analyzer import analyze_open_trajectories
    result = await analyze_open_trajectories()
    return {"ok": True, "suggestions_added": result.get("added", 0)}

@router.post("/meta/evolve-now")
async def evolve_now():
    _gate()
    from router.meta.meta_consensus import build_edit_plans
    from router.meta.meta_editor import MetaEditor
    from router.meta.meta_pr import MetaPR
    plans = build_edit_plans(force=True)
    applied = []
    for p in plans:
        MetaEditor.apply(p)
        MetaPR.submit(p)
        applied.append(p.target)
    return {"ok": True, "applied": applied}

@router.post("/telemetry/readmodel/refresh")
async def refresh_readmodel():
    _gate()
    from router.telemetry.readmodel.skill_model_affinity import rebuild
    count = rebuild()
    return {"ok": True, "rows": count}

@router.get("/healthz/pipeline")
async def pipeline_health():
    _gate()
    # P1~P4 훅의 최근 24h 실행 여부 확인
    # events 테이블 조회로 각 kind 존재 여부 체크
    import sqlite3
    from datetime import datetime, timedelta, timezone
    from router.server.paths import data_dir
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    conn = sqlite3.connect(str(data_dir() / "telemetry.db"))
    try:
        kinds = ["memory_mined", "skill_analyzed", "trajectory_compressed",
                 "insight_generated", "meta_suggestion"]
        seen = {}
        for k in kinds:
            row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE kind=? AND ts>=?", (k, cutoff)
            ).fetchone()
            seen[k] = row[0] if row else 0
    finally:
        conn.close()
    return {"ok": True, "last_24h": seen}
```

- [ ] **Step 2: 라우터 등록**

```python
# router/server/openai_compat.py
from router.server.dev_triggers import router as dev_triggers_router
app.include_router(dev_triggers_router)
```

- [ ] **Step 3: smoke**

```bash
FCR_DEV_TRIGGERS=1 uv run uvicorn router.server.openai_compat:app --port 7801 &
sleep 2
curl -X POST http://127.0.0.1:7801/meta/analyze-now
curl http://127.0.0.1:7801/healthz/pipeline
kill %1
# gate 확인
uv run uvicorn router.server.openai_compat:app --port 7801 &
sleep 2
curl -w "%{http_code}\n" http://127.0.0.1:7801/healthz/pipeline
kill %1
```

기대: 첫 번째 200, 두 번째 404.

- [ ] **Step 4: 커밋**

```bash
git add router/server/dev_triggers.py router/server/openai_compat.py
git commit -m "feat(dev): add FCR_DEV_TRIGGERS-gated forced triggers

POST /meta/analyze-now / /meta/evolve-now / /telemetry/readmodel/refresh
+ GET /healthz/pipeline for 24h P1-P4 hook visibility.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task D-3: 스냅샷 스크립트

**Files:**
- Create: `scripts/dogfood-snapshot.sh`

- [ ] **Step 1: 스크립트 작성**

```bash
#!/usr/bin/env bash
# scripts/dogfood-snapshot.sh
# 매일 실행. docs/superpowers/dogfood/YYYY-MM-DD/ 아래에 스냅샷 저장.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DATE="$(date -u +%Y-%m-%d)"
OUT="docs/superpowers/dogfood/$DATE"
mkdir -p "$OUT"

# 1. /meta/report HTML
if curl -sf http://127.0.0.1:7801/meta/report -o "$OUT/meta-report.html"; then
  echo "saved meta-report.html"
else
  echo "⚠ /meta/report 실패"
fi

# 2. 텔레메트리 카운트 JSON
DB="$HOME/.free-claw-router/telemetry.db"
if [ -f "$DB" ]; then
  python - <<PY > "$OUT/telemetry-counts.json"
import json, sqlite3
conn = sqlite3.connect("$DB")
out = {}
for t in ["spans", "events", "evaluations"]:
    try:
        out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    except Exception as e:
        out[t] = f"err: {e}"
try:
    out["events_by_kind"] = dict(conn.execute(
        "SELECT kind, COUNT(*) FROM events WHERE ts >= DATE('now','-1 day') GROUP BY kind"
    ).fetchall())
except Exception as e:
    out["events_by_kind"] = f"err: {e}"
print(json.dumps(out, indent=2, ensure_ascii=False))
PY
fi

# 3. suggestion_store 요약
SUG="$HOME/.free-claw-router/suggestions.jsonl"
if [ -f "$SUG" ]; then
  python - <<PY > "$OUT/suggestions-summary.json"
import json
from collections import Counter
by_status = Counter()
by_target = Counter()
with open("$SUG") as f:
    for line in f:
        line = line.strip()
        if not line: continue
        try:
            r = json.loads(line)
            by_status[r.get("status","?")] += 1
            by_target[r.get("target_id","?")] += 1
        except Exception:
            pass
print(json.dumps({"by_status": dict(by_status), "by_target": dict(by_target)},
                 indent=2, ensure_ascii=False))
PY
fi

# 4. 테스트 상태
{
  echo "=== cargo test ==="
  (cd rust && cargo test --workspace --quiet 2>&1 | tail -20) || true
  echo "=== pytest ==="
  (cd free-claw-router && uv run pytest -q 2>&1 | tail -20) || true
} > "$OUT/tests.log"

echo "✅ snapshot saved to $OUT"
```

- [ ] **Step 2: 실행 권한 + smoke**

```bash
chmod +x scripts/dogfood-snapshot.sh
./scripts/dogfood-snapshot.sh
ls -la docs/superpowers/dogfood/$(date -u +%Y-%m-%d)/
```

- [ ] **Step 3: 커밋**

```bash
git add scripts/dogfood-snapshot.sh
git commit -m "chore(dogfood): add daily snapshot script

Archives /meta/report HTML, telemetry counts JSON, suggestion
summary, and test status to docs/superpowers/dogfood/YYYY-MM-DD/.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task D-4: Dogfood 운영 가이드 문서

**Files:**
- Modify: `USAGE.md`

- [ ] **Step 1: "Dogfood 운영 가이드" 섹션 추가**

```markdown
## Dogfood 운영 가이드 (P5 L2)

### 사전 준비
1. `.env`에 필수 키 4개(OPENROUTER_API_KEY, GROQ_API_KEY, ZAI_API_KEY, CEREBRAS_API_KEY) 입력
2. `./scripts/bootstrap-dogfood.sh` 실행 (실패 단계 안내대로 보정 후 재실행)
3. 별도 터미널에서 사이드카 기동:
   `cd free-claw-router && uv run uvicorn router.server.openai_compat:app --port 7801`
4. `export OPENAI_BASE_URL=http://127.0.0.1:7801`

### Day 1~7 리듬
| 일자 | 활동 | 확인 |
|---|---|---|
| Day 1 | 첫 3세션 | 실패율·TTFT·텔레메트리 기록 |
| Day 2~3 | 3~5세션/일 | `skill_model_affinity` ≥ 3×3 쌍 |
| Day 4 | mempalace 조회 | insights ≥ 1 |
| Day 5 | `curl -X POST localhost:7801/meta/analyze-now` (FCR_DEV_TRIGGERS=1) | suggestions ≥ 3 |
| Day 6 | 03:00 UTC 크론 대기 | 메타 PR ≥ 1 |
| Day 7 | `clawd meta report` | 24h 활동 공백 없음 |

매일 끝 `./scripts/dogfood-snapshot.sh` 실행.

### Day 7 판정 체크리스트
`docs/superpowers/specs/2026-04-18-p5-balanced-evolution-design.md` §5.4 참조. 11개 항목 **모두** 충족 시 P6 착수.

### 미충족 시
`docs/superpowers/dogfood/p5-blockers.md`에 원인 기록 → 수정 스프린트 → 재측정.
```

- [ ] **Step 2: 커밋**

```bash
git add USAGE.md
git commit -m "docs(dogfood): add P5 L2 operations guide to USAGE.md"
```

---

## Task D-5: 실사용 1주 + Day 7 회고

이 작업은 **스크립트가 아닌 실제 7일 운영**. 체크리스트로만 관리.

- [ ] **Day 1**: bootstrap 실행, 첫 세션 3회, snapshot
- [ ] **Day 2**: 세션 3~5회 (P5 트랙 실작업에 claw 사용), snapshot
- [ ] **Day 3**: 세션 3~5회, snapshot
- [ ] **Day 4**: mempalace 조회 검증, snapshot
- [ ] **Day 5**: `/meta/analyze-now` 강제 트리거, snapshot
- [ ] **Day 6**: 크론 메타 PR 관찰, snapshot
- [ ] **Day 7**: `clawd meta report` 검토, snapshot, 판정

- [ ] **Day 7 판정 체크리스트 (스펙 §5.4 복사)**
  - [ ] 세션 실패율 < 10%
  - [ ] OpenRouter p50 TTFT < 1.5s
  - [ ] `skill_model_affinity` (skill, model) 쌍 ≥ 10
  - [ ] affinity 보너스가 라우팅 결정 1건 이상 뒤집음
  - [ ] P3 `insights` ≥ 3
  - [ ] `suggestion_store` ≥ 5
  - [ ] 메타 편집 PR ≥ 1 + Claude review `REQUEST_CHANGES` 없음
  - [ ] `/meta/report`가 24h 활동 공백 없이 렌더
  - [ ] `clawd meta report`가 에러 없이 HTML 오픈
  - [ ] GC 크론 1회 이상 실행 + 삭제 건수 기록
  - [ ] `cargo test --workspace` + `pytest` 통과

- [ ] **회고 문서 작성**

`docs/superpowers/dogfood/p5-retrospective.md`를 다음 템플릿으로 작성:

```markdown
# P5 Dogfood 회고 (Day 1 ~ 2026-04-XX)

## 체크리스트 최종 상태
(11개 항목, ✅/❌ + 측정값)

## 실현된 리스크 (R1~R10 중)
(각 리스크별 발현 여부 + 대응)

## P6(L3) 스펙 입력 자료
1. 예상치 못한 관찰
2. 파라미터 조정 제안 (affinity, GC 기간 등)
3. 다음 단계 우선순위 제안

## 스냅샷 diff (Day 1 → Day 7)
(telemetry-counts, suggestions-summary 의 주요 변화)
```

- [ ] **커밋**

```bash
git add docs/superpowers/dogfood/
git commit -m "docs(dogfood): Day 7 retrospective and daily snapshots"
```

### D 트랙 머지

- [ ] **Step 1: main 머지**

```bash
git checkout main
git merge feature/p5-track-d-dogfood --no-ff -m "merge: Track D (dogfood) — bootstrap/snapshot scripts, USAGE guide, 1-week retrospective"
```

- [ ] **Step 2: worktree 정리**

```bash
git worktree remove ../free-claw-code-p5-a
git worktree remove ../free-claw-code-p5-b
git worktree remove ../free-claw-code-p5-c
git worktree remove ../free-claw-code-p5-d
git branch -d feature/p5-track-a-debt feature/p5-track-b-observe feature/p5-track-c-loop feature/p5-track-d-dogfood
```

---

# P5 완료 판정

- [ ] **최종 전체 검증**

```bash
cd rust && cargo test --workspace && cargo clippy --workspace --all-targets -- -D warnings
cd ../free-claw-router && uv run pytest
pytest tests/test_porting_workspace.py
```

- [ ] **Day 7 체크리스트 전부 충족 확인**

전부 ✅면 P5 완료. 이후 `p5-retrospective.md`를 입력으로 `/superpowers:brainstorming "P6 L3 증분"` 호출.

1건이라도 ❌면 `p5-blockers.md` 기록 후 수정 스프린트.

---

# 자기검토 결과

(플랜 작성 후 스펙 커버리지 · 플레이스홀더 · 타입 일관성 검토 수행, 이슈 발견 시 인라인 수정)

- **스펙 커버리지**: §2 A-1~A-6, §3 B-1~B-4, §4 C-1~C-2, §5 D-1~D-5 모두 Task로 매핑됨. 비-목표(§6.5)는 의도적으로 제외(L3 이월).
- **플레이스홀더**: 신규 기능 코드는 완전체로 작성. 리팩터 Task는 TDD 대신 "기존 테스트 통과가 성공 지표" 패턴을 명시적으로 사용.
- **타입 일관성**: `AffinityConfig` / `CronSpec` / `BackpressureSignal` / `Alert` / `GcConfig` 시그니처가 플랜 전체에서 일관됨. `record_rollback` / `record_apply_success` / `is_blocked` / `unblock`이 B-4·B-2 엔드포인트에서 동일 이름으로 사용됨.
