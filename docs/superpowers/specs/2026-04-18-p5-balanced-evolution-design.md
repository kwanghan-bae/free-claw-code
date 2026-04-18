# P5 — 밸런스드 진화 (L2)

- **작성일**: 2026-04-18
- **작성자**: kwanghan-bae (Joel) + Claude
- **선행 페이즈**: P0~P4 (main 병합 완료 — 2026-04-16 ~ 2026-04-17)
- **후속 페이즈**: P6 (L3 하드코어 증분) — P5 Day 7 회고 문서 수신 후 착수
- **스코프 레벨**: Level 2 (밸런스드 — `CLAUDE.md` 및 브레인스토밍 세션 2026-04-18 결정)

## 0. 요약

P0~P4로 5층 자기진화 루프(무료 라우터 → 메모리 → 스킬 자기수정 → 학습 → 메타 자기수정)가 완성됐다. P5는 이 루프를 **실사용에 견딜 수 있는 상태**로 안정화한다. 4트랙을 병렬로 진행:

- **Track A — 부채 정리**: Rust 거대 파일 2개(`main.rs` 11.8K LOC, `tools/lib.rs` 9.7K LOC) 내부 모듈화, `openai_compat.py` 관심사 분리, P0 이월 2건(CronCreate 브릿지 · axum backpressure) 해소, clippy 경고 격리.
- **Track B — 관측 & 안전**: 로컬 HTML 감사 리포트(`/meta/report`), CLI 알림 훅(`clawd meta ...`), 3대 스토어 GC 정책, 연속 회귀 시 타깃 자동 블록.
- **Track C — 루프 심화**: `skill_model_affinity` → `routing/score.py` 실연결(베이지안 평탄화), SSE 스트리밍(OpenRouter 우선).
- **Track D — 1주 dogfood**: 부트스트랩 스크립트·운영 리듬·Day 7 판정 체크리스트·회귀 스냅샷. P5→P6 인수인계 계약.

단일 P5 스펙 + 4-트랙 병렬 worktree + 통합 리뷰 체크포인트 1회 구조.

## 1. 아키텍처 & 실행 구조

### 1.1 실행 토폴로지

```
main
  ├─ feature/p5-track-a-debt       (worktree 1)
  ├─ feature/p5-track-b-observe    (worktree 2)
  ├─ feature/p5-track-c-loop       (worktree 3)
  └─ feature/p5-track-d-dogfood    (worktree 4, 후반 활성화)
```

- A/B/C는 Day 1부터 병렬. `superpowers:subagent-driven-development`로 서브에이전트 3개 동시 디스패치.
- D는 A/B/C의 **필수 선행 항목이 모두 머지된 시점**부터 개시. 구체적 선행 조건:
  - A-4 (CronCreate 브릿지) 머지됨
  - B-1 (`/meta/report`) + B-2 (`clawd meta *` 명령 최소 `report`) 머지됨
  - C-1 (affinity 보너스가 `routing/score.py`에 실연결, 라우팅 결정 events 기록 시작)
  - 나머지 항목(A-1/A-2 분할, A-3/C-2, B-3 GC, B-4 블록, A-5 backpressure)은 D와 병렬 진행 허용
- 이 조건만으로 "70% 완료"를 정의 — 체감 진척도 대신 명시적 게이트.
- 통합 리뷰 체크포인트: D 개시 직전, 임시 `feature/p5-integration`에서 A/B/C 머지 프리뷰 + `cargo test --workspace` + `pytest` 동시 통과 확인.

### 1.2 머지 흐름

1. P5 스펙 + 갱신된 `CLAUDE.md` 동반 커밋을 `main`에 직접 머지 (P5 킥오프)
2. 각 트랙 worktree에서 개발 → feature 브랜치 → `main` 직접 머지 (PR 절차 생략, 사용자 선호)
3. D 완료 후 P6 스펙 작성 착수

### 1.3 의존성 그래프

```
A (부채)     ─┐
B (관측)     ─┼─> 통합 리뷰 ──> D (dogfood) ──> P6 스펙
C (루프 심화) ─┘
```

### 1.4 트랙 간 파일 잠금 규칙

병렬 충돌을 0으로 만들기 위해 다음 순서를 강제:

- **`openai_compat.py`**: A-3(분리) → C-2(SSE 추가) 순.
- **텔레메트리 이벤트 스키마**: C-1(affinity 이벤트 추가) → B-1(대시보드 렌더).
- **Rust `crates/commands/`**: A-1 완료 후 B-2의 `clawd meta *` 명령 추가.

## 2. Track A — 부채 정리

외부 API 불변을 원칙. 내부 모듈 경계만 재조직하여 `meta_targets.yaml` 편집 대상 경로에 영향을 주지 않는다.

### 2.1 `rust/crates/rusty-claude-cli/src/main.rs` 분할 (11,816 LOC)

같은 crate 내부에서 sibling 모듈로 쪼갠다(서브크레이트화는 L3로 이월):

```
main.rs                ← 엔트리 + 핸들러 배선만 (목표 < 500 LOC)
session_lifecycle.rs   ← 세션 시작 / resume / compact 루틴
bash_validation.rs     ← 기존 존재, 링크만 정리
command_dispatch.rs    ← 슬래시 명령 라우팅
permissions_runtime.rs ← 런타임 퍼미션 강제
output_format.rs       ← compact / verbose 출력 포맷
date_utils.rs          ← clippy `similar_names` 대상 격리
```

- 분할 후 `pub use`로 경로 보존하여 통합 테스트 수정 0.
- 분할 전 `rg '::main::' rust/` 및 bin crate 호출 경로 전수 조사.

### 2.2 `rust/crates/tools/src/lib.rs` 분할 (9,748 LOC)

개념별 디렉터리:

```
tools/src/
  ├─ bash/
  ├─ browser/
  ├─ git/
  ├─ lsp/
  ├─ search/
  ├─ file/
  └─ lib.rs            ← facade: 기존 심볼 `pub use`
```

- facade 유지로 외부 crate `use tools::...` 경로 불변.

### 2.3 `free-claw-router/router/server/openai_compat.py` 4-분리 (304 LOC)

```
openai_compat.py             ← FastAPI 라우트 + 배선 (목표 ≤ 100 LOC)
_telemetry_middleware.py     ← span/trace 삽입·종료
_quota_middleware.py         ← 쿼터 체크·차감
_injection.py                ← P1 메모리 주입 + P3 넛지
```

`_` prefix로 내부 모듈 시그널.

### 2.4 Rust `CronCreate` → 사이드카 `/cron/register` 브릿지 (P0 Task 47)

- `rust/crates/commands/src/cron.rs`에 `register_cron` 함수 신설.
- 사이드카 엔드포인트는 `router/server/openai_compat.py:291-300`에 이미 존재.
- HTTP 클라이언트: 기존 워크스페이스 의존성 `reqwest`.
- 실패 시 로컬 `~/.claude/cron/` fallback 유지 (회복력).

### 2.5 axum `/internal/backpressure` 리스너 (P0 Task 8 Step 3)

- `rust/crates/runtime/src/backpressure_server.rs` 신설.
- 워크스페이스 deps에 `axum = "0.7"` 추가.
- `POST /internal/backpressure` — JSON `{level: str, reason: str}` 수신 → 런타임 rate limiter 반영.
- bind: 127.0.0.1 전용.

### 2.6 clippy `similar_names` 해소

- A-1에서 `date_utils.rs`로 격리 완료된 후 파일 상단 `#![allow(clippy::similar_names)]` + 주석 `// date-of-era / day-of-year 표준 변수명`.

### 2.7 산출물

- Rust: 7개 신규 모듈 파일, `Cargo.toml` axum 추가, `commands/src/cron.rs` 신설.
- Python: 3개 신규 파일(`_telemetry_middleware.py`, `_quota_middleware.py`, `_injection.py`), `openai_compat.py` 축소.
- 테스트: 기존 테스트 전부 통과해야 함. 신규 테스트는 A-4(CronCreate 브릿지)와 A-5(backpressure)만 추가.

## 3. Track B — 관측 & 안전 강화

### 3.1 로컬 HTML 감사 리포트 (`/meta/report`)

- 엔드포인트: `GET /meta/report` → `router/server/meta_report.py`(신설)가 정적 HTML 반환.
- 의존성 추가 없음. Vanilla HTML + 인라인 CSS(~100 LOC). 서버에서 SVG polyline 생성.
- 렌더 섹션 (상→하):
  1. 최근 24h 메타 활동 요약 (제안·표결·적용·롤백 수)
  2. 편집 대상별 제안 history 타임라인 (10개 타깃 각각)
  3. 자기수정 PR 상태판 (열림·머지·자동 롤백, GH API 1회 캐시)
  4. 평가 추이 차트 (`evaluations.score_dim`별 7일 이동평균)
  5. 미해결 경고 (연속 degradation, 롤백 근접 PR, GC 임박)
- 데이터 소스: `telemetry.db`(spans/evaluations/events) + `suggestion_store`(JSONL).
- 인증 레이어 없음 — 127.0.0.1 바인딩만으로 보호.

### 3.2 CLI 알림 훅 (`clawd meta ...`)

- `meta_evaluator.py`가 평가 후 `events` 테이블에 `meta_alert` 이벤트 기록(레벨 `info` / `warn` / `critical`).
- Rust 신규 명령 (`crates/commands/src/meta_cmd.rs`):
  - `clawd meta report` → macOS `open` / Linux `xdg-open`으로 `/meta/report` URL 열기.
  - `clawd meta alerts --json` → 대기 경고 JSON.
  - `clawd meta ack <id>` → critical 경고 해제.
  - `clawd meta unblock <target>` → B-4 자동 블록 해제.
- CLI 기동 배너: `critical` 경고 대기 중이면 상단에 "⚠ 메타 경고 N건 — `clawd meta report`".

Slack·웹훅은 L3(P6)로 이월.

### 3.3 스토어 GC 정책

| 스토어 | 위치 | 정책 |
|---|---|---|
| `suggestion_store` | `~/.free-claw-router/suggestions.jsonl` | 적용 완료 30일 / 기각 7일 / 대기 유지. 일일 03:15 UTC. |
| trajectory mempalace | mempalace 지갑 | 압축 궤적 90일 / 원본 세션 180일. 지갑 상한 1GB 초과 시 오래된 순 삭제. |
| `telemetry.db` | `~/.free-claw-router/telemetry.db` | spans 30일 / events 90일 / evaluations 180일. 주 1회 `VACUUM`. |

- 구현: `router/server/gc.py`(신설) + APScheduler 등록 `router/server/lifespan.py`.
- **2단 커밋**: 삭제 전 dry-run 카운트를 `events` 테이블에 기록. 다음 실행에서 확인 후 실제 삭제. 사고 복구 1일 여유.
- 환경 변수 오버라이드: `FCR_GC_SPAN_DAYS` / `FCR_GC_SUGGESTION_DAYS` 등 — 장기 실험 시 GC 중단 가능.
- B-3은 `telemetry.db` 스키마에 메타데이터 추가 시 **다운 마이그레이션 스크립트 동반 필수**.

### 3.4 자기수정 회귀 강화

- `meta_evaluator.py`가 연속 2회 롤백된 타깃을 감지하면:
  - `suggestion_store`에서 해당 `target_id` 제안 자동 기각
  - `meta_alert` (레벨 `critical`) 발생
- 수동 해제: `clawd meta unblock <target>`.
- 목적: 특정 프롬프트가 반복 열화되는 루프를 사람이 개입할 때까지 중단.

### 3.5 산출물

- `router/server/meta_report.py` (신설, ~200 LOC)
- `router/server/gc.py` (신설, ~150 LOC)
- `router/meta/meta_evaluator.py` (수정, ~30 LOC 증가)
- `rust/crates/commands/src/meta_cmd.rs` (신설)
- `CLAUDE.md` "핵심 계약·불변식" 섹션에 GC 정책·블록 정책 추가

## 4. Track C — 루프 심화

### 4.1 `skill_model_affinity` → `routing/score.py` 실연결

현재 읽기모델 테이블은 존재하지만 `routing/score.py`가 참조하지 않는 dead loop. P5에서 실제 연결.

- `routing/score.py:score_candidate()`에 `affinity_bonus` 추가:
  ```
  score = base + tool_use_bonus + context_window_bonus + affinity_bonus(skill_id, model_id)
  ```
- `affinity_bonus` 계산 (`router/routing/affinity.py` 신설):
  - 최근 30일 성공률 `s` (0.0~1.0), 표본 수 `n`.
  - 베이지안 평탄화: `adjusted = (s*n + 0.5*PRIOR_N) / (n + PRIOR_N)`, `PRIOR_N=10`.
  - 보너스 = `(adjusted - 0.5) * AFFINITY_WEIGHT`, `AFFINITY_WEIGHT=0.3`.
  - 클리핑: `[-0.15, +0.15]`.
- `skill_id` 누락 시 보너스 0 (기존 경로 완전 호환).
- 각 라우팅 결정 `events`에 `kind="routing_decision"`, `payload={"candidates":..., "affinity_applied":...}` 기록.
- 파라미터(`AFFINITY_WEIGHT`·`PRIOR_N`·클리핑 범위)는 `meta_targets.yaml`에 `config_only` 타입으로 등록 → P4가 스스로 가중치 조정 가능(재귀 심화).

검증: `free-claw-router/tests/test_routing_affinity.py`(신설).
- cold-start → 보너스 0.
- 고성공(30/30) → +0.15 클리핑.
- 저성공(0/30) → -0.15 클리핑.
- skill_id 없음 → 정적 정책과 동일.

### 4.2 SSE 스트리밍 디스패치 (OpenRouter 우선)

- 수신: `openai_compat.py`(A-3 분리 후 슬림해진 라우트 파일)에서 `stream=true` 감지 → `StreamingResponse(generator, media_type="text/event-stream")`.
- 디스패치: `router/dispatch/sse.py`(신설):
  ```
  async def dispatch_sse(provider, request) -> AsyncIterator[bytes]:
      async with httpx.AsyncClient(timeout=None) as client:
          async with client.stream("POST", url, json=req, headers=hdr) as resp:
              async for chunk in resp.aiter_bytes():
                  yield chunk
  ```
- 첫 chunk 전 실패 시 기존 fallback 체인. 첫 chunk 후 실패는 `event: error` 주입.
- **헤더 `X-Accel-Buffering: no`** 필수 — 프록시 버퍼링 방지.
- 텔레메트리:
  - span 시작: 첫 chunk 수신 시점.
  - span 종료: `[DONE]` 또는 연결 종료.
  - 실시간 tool_call 파싱은 L3로 이월. L2는 최종 집계만.
  - 토큰 카운트: provider `usage` 청크에서 수집. 미지원 provider는 SSE 미지원으로 표시.
- provider 범위 (L2):
  - **OpenRouter** 필수.
  - **Groq**: 여력 시 포함. 없으면 L3.
  - z.ai / Cerebras / Ollama / LM Studio: L3.
- `catalog/data/*.yaml`에 `capabilities.sse: true` 필드 추가. `provider_supports_sse(provider_id)` 유틸이 미지원 provider를 non-SSE로 자동 강등.
- Rust 측: 기존 `crates/api/src/providers/openai_compat.rs`가 `stream=true` 전달 가능. 수신 파싱은 기존 OpenAI SDK 호환 코드 재사용.

검증:
- `free-claw-router/tests/test_sse_dispatch.py`: 정상/중단/강등.
- `rust/crates/api/tests/openai_compat_integration.rs`에 SSE 시나리오 추가.
- 실측(D-4): OpenRouter p50 TTFT < 1.5s, non-stream 대비 -70%.

### 4.3 트랙 내부 순서

1. C-1 (affinity 연결) — B-1 시작 전 이벤트 스키마 확정.
2. C-2 (SSE, OpenRouter) — A-3 완료 후.
3. C-2 확장 (Groq) — 여력 시.

### 4.4 산출물

- `router/routing/score.py` (수정)
- `router/routing/affinity.py` (신설)
- `router/dispatch/sse.py` (신설)
- `router/server/openai_compat.py` (수정, streaming 분기)
- `router/catalog/data/*.yaml` (capabilities.sse 필드 추가)
- `router/meta/meta_targets.yaml` (affinity config 등록)
- 테스트 2건.

## 5. Track D — 1주 dogfood

### 5.1 부트스트랩 스크립트 (`scripts/bootstrap-dogfood.sh`)

idempotent. 실패 단계를 명확히 안내.

```
1. .env 필수 키 점검 (OPENROUTER_API_KEY / GROQ_API_KEY / ZAI_API_KEY / CEREBRAS_API_KEY, 선택 ANTHROPIC_API_KEY)
2. mempalace init ~/projects
3. OpenSpace MCP 검증 (python -m openspace.mcp_server --check)
4. 사이드카 기동 확인 (curl 127.0.0.1:7801/healthz)
5. Rust CLI 빌드 (cargo build --release -p rusty-claude-cli)
6. OPENAI_BASE_URL export 안내
7. 텔레메트리 초기화 확인
```

`USAGE.md`에 "Dogfood 부트스트랩" 섹션 추가.

### 5.2 운영 리듬 (Day 1~7)

| 일자 | 활동 | 수집 지표 |
|---|---|---|
| Day 1 | 부트스트랩 + 첫 세션 3회 | 실패율·TTFT·기본 텔레메트리 |
| Day 2~3 | 실사용 3~5세션/일 (P5 트랙 작업 자체에 claw 사용, 세션 = 한 번의 `clawd` 프로세스 기동부터 종료까지, 최소 1개 tool call 포함) | `skill_model_affinity`에 ≥ 3×3 쌍 |
| Day 4 | mempalace 조회·P3 궤적 압축 확인 | 압축 궤적 ≥ 10, insights ≥ 1 |
| Day 5 | `POST /meta/analyze-now` 강제 트리거 | suggestions ≥ 3 |
| Day 6 | 일일 03:00 UTC 크론 대기 → 메타 PR 관찰 | PR ≥ 1, Claude review에 `REQUEST_CHANGES` 없음 |
| Day 7 | `/meta/report` 감사 + 회귀 점검 | 스냅샷·P6 입력 자료 |

"P5 작업을 P5 에이전트로" 재귀 dogfood: D 기간 중 P5 코드 작업 자체를 claw로 수행.

### 5.3 개발자 편의 강제 트리거 (`router/server/dev_triggers.py`)

환경변수 `FCR_DEV_TRIGGERS=1`이 없으면 404. 켜면:

```
POST /meta/analyze-now             — MetaAnalyzer 즉시 실행
POST /meta/evolve-now              — build_edit_plans 즉시 호출
POST /telemetry/readmodel/refresh  — skill_model_affinity 재계산
GET  /healthz/pipeline             — P1→P2→P3→P4 훅 최근 24h 실행 여부
```

### 5.4 Day 7 판정 체크리스트

P6 진입 전 **모두 충족** 필요:

- [ ] 세션 실패율 < 10% (최근 7일)
- [ ] OpenRouter p50 TTFT < 1.5s
- [ ] `skill_model_affinity` (skill, model) 쌍 ≥ 10
- [ ] affinity 보너스가 라우팅 결정 1건 이상 뒤집음 (events 조회 검증)
- [ ] P3 `insights` ≥ 3
- [ ] `suggestion_store` ≥ 5
- [ ] 메타 편집 PR ≥ 1 자동 생성 + Claude review에 `REQUEST_CHANGES` 없음
- [ ] `/meta/report`가 24h 활동을 공백 없이 렌더
- [ ] `clawd meta report` 에러 없이 HTML 오픈
- [ ] GC 크론 1회 이상 실행 + 삭제 건수 기록
- [ ] `cargo test --workspace` + `pytest` 통과 유지

1건이라도 미충족 시 P6 착수 대기. 원인을 `docs/superpowers/dogfood/p5-blockers.md`에 기록 후 수정 스프린트.

### 5.5 회귀 포착 (`scripts/dogfood-snapshot.sh`)

매일 실행, `docs/superpowers/dogfood/YYYY-MM-DD/`에 아카이브:
- `/meta/report` HTML
- `telemetry.db` 핵심 카운트 JSON 덤프
- `suggestion_store` 요약
- 테스트 상태

Day 7에 Day 1 대비 diff 자동 생성 → P6 스펙 입력 자료.

### 5.6 의존성

- D는 A-4 이후 개시 (CronCreate 브릿지 없이는 Rust 쪽 크론 등록 불가).
- B-1·B-2 없으면 Day 7 체크리스트가 수작업 SQL 조회로 변질 → B가 D 선행.
- C-1 없으면 "라우팅 결정 뒤집음" 검증 불가 → C-1이 D 선행.

### 5.7 산출물

- `scripts/bootstrap-dogfood.sh`, `scripts/dogfood-snapshot.sh` (신설)
- `USAGE.md` Dogfood 가이드 섹션
- `router/server/dev_triggers.py` (신설, 게이트)
- `docs/superpowers/dogfood/` (신설 디렉터리, 7일치 스냅샷)
- `docs/superpowers/dogfood/p5-retrospective.md` (Day 7 회고)

## 6. 성공 기준·리스크·롤백

### 6.1 P5 전체 성공 기준

P5 머지 시점에 다음을 **모두** 만족:

1. Rust 거대 파일 2개가 모듈화되어 **외부 API 불변**으로 유지됨.
2. 메타 자기수정이 **실사용 트래픽**에서 PR을 1건 이상 자연 생성.
3. 로컬 감사 대시보드에서 지난 7일의 모든 제안·투표·편집·롤백이 공백 없이 보임.
4. `cargo test --workspace` + `pytest` + 포팅 패리티 모두 통과.

하나라도 Day 7에 미충족 시 "part-1 shipped, part-2 pending"으로 표시하고 P6 착수 대기.

### 6.2 리스크 레지스터

| # | 리스크 | 확률 | 영향 | 완화 |
|---|---|---|---|---|
| R1 | `main.rs` 분할 중 공개 re-export 누락으로 하위 crate 컴파일 에러 | 중 | 중 | 분할 후 `cargo build --workspace` + integration test 전량. PR 단위 수직 슬라이스. |
| R2 | `tools/lib.rs` 분할 후 매크로/trait 암묵 상속 파손 | 중 | 중 | facade `pub use` 전체 재수출. 분할 전 `rg 'tools::' --type rust` 전수 조사. |
| R3 | SSE passthrough에서 HTTP/2 keep-alive·프록시 버퍼링으로 chunk 뭉침 | 중 | 중 | `StreamingResponse` + `X-Accel-Buffering: no`. 로컬 재현 테스트. |
| R4 | affinity cold-start 편향으로 특정 모델 극단 선호 | 중 | 고 | `PRIOR_N=10` + `AFFINITY_WEIGHT=0.3` + 클리핑 `[-0.15, +0.15]` 3중 완충. D-4 라우팅 이벤트 감사. |
| R5 | GC가 활성 스토어 삭제로 감사 지표 손실 | 저 | 고 | 2단 커밋(dry-run → 다음 실행 삭제) + 환경변수 정지 + 삭제 건수 `events` 기록. |
| R6 | dogfood 중 Free-tier 쿼터 소진 | 중 | 중 | 4개 provider 키 사전 점검. 70% 임계치 `meta_alert`. |
| R7 | 자기수정 PR이 `meta_targets.yaml` 자체 열화 | 저 | 극고 | 기존 가드레일 + B-4 연속 2회 롤백 자동 블록. |
| R8 | A/B/C 병렬 중 `openai_compat.py` 동시 쓰기 | 중 | 저 | A-3 → C-2 순서 강제. 트랙 디스패치 전 lockfile 선언. |
| R9 | 사이드카 재기동 누락으로 구버전 코드 실행 | 중 | 저 | 부트스트랩 `--restart` 옵션. 머지 후 1회 실행 의무. |
| R10 | P6 스코프가 L2 회고 없이 확장되어 의도 이탈 | 저 | 중 | P6 브레인스토밍은 `p5-retrospective.md` 필수 입력. |

### 6.3 롤백 전략

트랙 단위 롤백이 원칙:

- **A**: `git revert <merge-commit>`. 외부 API 불변이므로 소비자 영향 없음.
- **B**: `meta_report.py`·`gc.py`·`clawd meta *` 제거. 순수 추가물이라 기존 동작 무영향.
- **C**:
  - C-1: `AFFINITY_WEIGHT=0` 런타임 무력화. 코드 잔존.
  - C-2: `provider_supports_sse(...)` 전면 False → 자동 강등. 코드 잔존.
- **D**: 불가(이미 실사용 발생). 결과 해석을 `p5-blockers.md`로 재조정.

통합 롤백: `main`을 P5 킥오프 직전으로 되감기. 단 B-3의 `telemetry.db` 스키마 변경은 **다운 마이그레이션 스크립트 동반 필수**.

### 6.4 P5 → P6 인수인계 계약

P6 스펙은 다음 네 가지를 **입력**으로만 받음:

1. `docs/superpowers/dogfood/p5-retrospective.md` (Day 7 회고)
2. `docs/superpowers/dogfood/2026-04-XX/` 7일치 스냅샷
3. Day 7 체크리스트 최종 상태 (전부 ✅ 또는 미충족 항목 명시)
4. R-레지스터 중 실현된 리스크 목록

이 네 가지 없이 P6 브레인스토밍 호출 금지.

### 6.5 비-목표 (명시적 L2 제외)

- 서브크레이트 분할 (`cli-core`, `cli-session` 등) — L3
- Slack·웹훅 알림 — L3
- Grafana 등 외부 관측 스택 — L3
- OpenSpace 커뮤니티 스킬 공유 — L3
- Hermes multi-key 크리덴셜 회전 — L3
- 스트리밍 중 실시간 tool_call 파싱 — L3
- z.ai / Cerebras / Ollama / LM Studio SSE — L3
- P6 스펙 사전 집필 — Day 7 회고 후

## 7. 참조

- `CLAUDE.md` — 2026-04-18 재작성본 (3-표면 / P0~P4 / 핵심 계약·불변식)
- `docs/superpowers/specs/2026-04-15-p0-free-llm-router-design.md`
- `docs/superpowers/specs/2026-04-16-p1-mempalace-memory-design.md`
- `docs/superpowers/specs/2026-04-16-p2-openspace-skill-evolution-design.md`
- `docs/superpowers/specs/2026-04-16-p3-hermes-learning-loop-design.md`
- `docs/superpowers/specs/2026-04-17-p4-hyperagent-meta-evolution-design.md`
- `PARITY.md` — Rust ↔ Python 패리티 기준선
- `ROADMAP.md` — 5단계 프로그램 상세
