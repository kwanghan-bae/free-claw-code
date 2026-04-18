# CLAUDE.md

Claude Code(claude.ai/code)가 이 저장소에서 작업할 때 참고하는 지침입니다.

## 프로젝트 정체성

`free-claw-code`는 무료 LLM만 사용하는 **자기진화 코딩 에이전트**(upstream: ultraworkers/claw-code 포크). P0~P4 5단계 루프가 `main`에 모두 머지되어 있습니다:

- **P0** 무료 LLM 라우터·쿼터·텔레메트리 사이드카
- **P1** Mempalace 세션 메모리·자동 마이닝
- **P2** OpenSpace 스킬 자기수정(FIX/DERIVED/CAPTURED)
- **P3** Hermes 학습 루프(nudge → batch → insight → trajectory 압축)
- **P4** HyperAgent 메타 자기수정(정책·프롬프트·thresh 편집 → 합의 → PR → 자동 롤백)

문서는 **한국어 우선**입니다. 영문 스펙은 번역 대기 대상.

## 3-표면(three-surface) 아키텍처

| 디렉터리 | 역할 | 언어 |
|---|---|---|
| `rust/` | **활성 런타임** — CLI, 플러그인, 텔레메트리, API 호환 (8 crates) | Rust 2021 |
| `src/` | **패리티 레퍼런스** — 원본 Python/TS 포트, 동작 기준선(ground truth) | Python |
| `free-claw-router/` | **라이브 사이드카** — FastAPI 라우터 + P1~P4 파이프라인 | Python 3.11+ |
| `tests/` | 크로스-표면 포팅 검증 (`test_porting_workspace.py`) | Python |

행동 변경 시 **세 표면을 한 번에 함께 갱신**해야 패리티·포팅 테스트가 통과합니다. `PARITY.md`가 캐노니컬 진행 상황.

## 검증

### Rust (`rust/`에서 실행)
```
cargo fmt --all
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```
현재 상태: 워크스페이스 전체 `clippy -D warnings` 통과.

### Python 사이드카 (`free-claw-router/`에서 실행)
```
uv run pytest
uv run ruff check .
```
로컬 기동: `uv run uvicorn router.server.openai_compat:app --port 7801`. claw는 `OPENAI_BASE_URL=http://127.0.0.1:7801`로 연결.

### 포팅 패리티 (루트에서)
```
pytest tests/test_porting_workspace.py
python rust/scripts/run_mock_parity_diff.py
```

## 핵심 계약·불변식

- **텔레메트리 스키마**(`router/telemetry/migrations/001_initial.sql`): `traces / spans / events / evaluations` 4테이블이 P2·P3·P4가 공용으로 소비하는 계약. 스키마 변경은 마이그레이션 파일 추가로만.
- **메타 편집 화이트리스트**(`free-claw-router/router/meta/meta_targets.yaml`): 자기수정 대상은 여기 등재된 파일만. 타입(`yaml` / `prompt_only` / `config_only`)도 강제. 임의 Rust·Python 로직 편집 금지.
- **자기수정 가드레일**: 최소 3세션 합의 + 일 2건 상한 + 5세션 평가 후 자동 롤백 + `gh pr` + Claude 리뷰 + **연속 2회 롤백 타깃 자동 블록**. 이 체인을 우회하는 코드는 머지 금지.
- **타깃 자동 블록**(P5 B-4): 동일 `meta_targets.yaml` 항목이 연속 2회 롤백되면 `suggestion_store`가 해당 타깃 제안을 자동 기각 + `critical` `meta_alert` 발화. 해제는 수동만 — `clawd` REPL에서 `/meta unblock <target>` 또는 `POST /meta/unblock/<target>`.
- **스토어 GC 정책**(P5 B-3): `spans` 30일 / `events` 90일 / `evaluations` 180일 / 제안 스토어 30일(`timestamp` 기준). 2단 커밋(dry-run → commit). 환경변수 오버라이드 `FCR_GC_SPAN_DAYS` / `FCR_GC_EVENT_DAYS` / `FCR_GC_EVAL_DAYS` / `FCR_GC_SUGGESTION_DAYS`, 전역 정지 `FCR_GC_PAUSED=1`. 일일 03:15 UTC 크론.
- **제안 스토어 경로·포맷**: `~/.free-claw-router/meta_suggestions.json` — JSON array, `MetaSuggestion` 스키마(`target_file`, `timestamp` float, `rationale`, ...). 읽기 consumer는 이 포맷을 기준으로 어댑팅. 파일명·포맷 변경은 `SuggestionStore` + `/meta/report` + `gc.py` 3군데 동시 수정 필요.
- **무료 전용 라우팅**(`router/routing/policy.yaml`): OpenRouter free / Groq / z.ai GLM / Cerebras / Ollama / LM Studio만 허용. 유료 provider 추가 금지.
- **스킬 모델 친화도 읽기모델**(`skill_model_affinity`)은 P2 OpenSpace 통합점 — 컬럼 제거·의미 변경 주의.

## 작업 원칙

- 작고 리뷰 가능한 단위로 커밋. 독립 작업은 **공격적으로 묶어서** 단일 서브에이전트 디스패치(사용자 선호).
- 내부 작업은 PR 절차 생략하고 feature 브랜치 → `main` 직접 머지 기본값(사용자 선호).
- 모든 문서는 한국어. 기존 영문 스펙(`docs/superpowers/specs/*.md`)은 점진적으로 번역 대상.
- 공유 기본값은 `.claude.json`에, 머신-로컬 오버라이드는 `.claude/settings.local.json`에.
- 이 `CLAUDE.md`는 워크플로·표면 구조·핵심 계약이 바뀔 때만 **의도적으로** 갱신. 자동 덮어쓰기 금지.

## 알려진 미완·부채

P5 Track A·B로 아래 이월 항목들은 해소됐습니다:
- ~~Rust `CronCreate` → `/cron/register` 브릿지~~ ✅ P5 A-4 (`commands::cron`)
- ~~`/internal/backpressure` HTTP 리스너~~ ✅ P5 A-5 (`runtime::backpressure_server`, axum 0.7)
- ~~`openai_compat.py` 304 LOC 관심사 혼재~~ ✅ P5 A-3 (3개 미들웨어로 분리, 118 LOC)
- ~~`main.rs` 11.8K LOC 거대 파일~~ ⚠ P5 A-1로 10.4K로 축소 + 6개 sibling 모듈화. 서브크레이트 분할은 L3 이월.
- ~~`tools/lib.rs` 9.7K LOC~~ ⚠ P5 A-2로 6개 카테고리 모듈화(bash/browser/git/lsp/search/file). facade 잔존 8.86K는 scope 외 도구(TodoWrite/Skill/Agent/Task/Worker/MCP) — L3 추가 카테고리 후보.
- ~~clippy `similar_names` 경고~~ ✅ P5 A-1.2 (`date_utils.rs`로 격리 + 파일 단위 allow)

남은 항목:
1. **Flaky test** `resume_latest_restores_the_most_recent_managed_session` (`rusty-claude-cli/tests/resume_slash_commands.rs:179`) — CWD 의존, 메인에서도 실패. 세션 스토어 복구 경로 조사 필요.
2. **Hermes `git subtree`** 다중 키 크리덴셜 회전 — env 어댑터만 동작 (L3).
3. **`analyzer_hook.py:23`** TODO — P2-M2 벤더 analyzer 연결 미완.
4. **B-4 call-site 연결** 대기 — `record_rollback`/`record_apply_success` 트래킹 함수는 있으나 실제 rollback/apply 코드 경로에 hook-up 안 됨. 5세션 평가 루프 설계 시 연결 예정.
5. **제안 스토어 경로·포맷 의존**: `meta_suggestions.json` JSON array + `MetaSuggestion` 스키마. 변경 시 3군데(`SuggestionStore` + `/meta/report` + `gc.py`) 동시 수정.

## 참조 문서

- `ROADMAP.md` — 5단계 프로그램 상세 계획 (86K)
- `PARITY.md` — Rust ↔ Python 패리티 현황 (14K)
- `PHILOSOPHY.md` — 한국어-우선 정체성 및 설계 철학
- `USAGE.md` — 실사용 가이드 (14K)
- `docs/superpowers/specs/` — P0~P4 단계별 설계 스펙·플랜 (영문, 번역 대기)
