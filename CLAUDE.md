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
현재 상태: clippy 통과(단, `rusty-claude-cli/src/main.rs:5761`의 `similar_names` 경고 1개는 잔존 — pedantic, CI 차단 아님).

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
- **자기수정 가드레일**: 최소 3세션 합의 + 일 2건 상한 + 5세션 평가 후 자동 롤백 + `gh pr` + Claude 리뷰. 이 체인을 우회하는 코드는 머지 금지.
- **무료 전용 라우팅**(`router/routing/policy.yaml`): OpenRouter free / Groq / z.ai GLM / Cerebras / Ollama / LM Studio만 허용. 유료 provider 추가 금지.
- **스킬 모델 친화도 읽기모델**(`skill_model_affinity`)은 P2 OpenSpace 통합점 — 컬럼 제거·의미 변경 주의.

## 작업 원칙

- 작고 리뷰 가능한 단위로 커밋. 독립 작업은 **공격적으로 묶어서** 단일 서브에이전트 디스패치(사용자 선호).
- 내부 작업은 PR 절차 생략하고 feature 브랜치 → `main` 직접 머지 기본값(사용자 선호).
- 모든 문서는 한국어. 기존 영문 스펙(`docs/superpowers/specs/*.md`)은 점진적으로 번역 대상.
- 공유 기본값은 `.claude.json`에, 머신-로컬 오버라이드는 `.claude/settings.local.json`에.
- 이 `CLAUDE.md`는 워크플로·표면 구조·핵심 계약이 바뀔 때만 **의도적으로** 갱신. 자동 덮어쓰기 금지.

## 알려진 미완·부채

P4까지의 이월 항목 — 작업 시작 전 현재 상태 확인 필요:

1. Rust `CronCreate` → 사이드카 `/cron/register` 브릿지 미연결 (Python 엔드포인트는 `router/server/openai_compat.py:291-300`에 대기)
2. `/internal/backpressure` HTTP 리스너 없음(axum 도입 필요, P0 Task 8 Step 3)
3. Hermes `git subtree` 다중 키 크리덴셜 회전 — env 어댑터만 동작
4. Flaky test `resume_latest_restores_the_most_recent_managed_session` (`rusty-claude-cli/tests/resume_slash_commands.rs:179`)
5. `openai_compat.py` 304 LOC 관심사 혼재(텔레메트리 + 쿼터 + P1 주입 + P3 넛지) — 모듈 분리 후보
6. `analyzer_hook.py:23` TODO — P2-M2 벤더 analyzer 연결 미완
7. 거대 파일: `rust/crates/rusty-claude-cli/src/main.rs`(11.8K LOC), `rust/crates/tools/src/lib.rs`(9.7K LOC) — 분할 후보

## 참조 문서

- `ROADMAP.md` — 5단계 프로그램 상세 계획 (86K)
- `PARITY.md` — Rust ↔ Python 패리티 현황 (14K)
- `PHILOSOPHY.md` — 한국어-우선 정체성 및 설계 철학
- `USAGE.md` — 실사용 가이드 (14K)
- `docs/superpowers/specs/` — P0~P4 단계별 설계 스펙·플랜 (영문, 번역 대기)
