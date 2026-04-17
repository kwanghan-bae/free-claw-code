# Free Claw Code

<p align="center">
  <img src="assets/claw-hero.jpeg" alt="Free Claw Code" width="300" />
</p>

**무료 LLM만으로 스스로 진화하는 코딩 에이전트.**

[ultraworkers/claw-code](https://github.com/ultraworkers/claw-code)를 포크하여, 무료 모델 전용 라우팅 · 초장기 기억 · 스킬 자가진화 · 능동 학습 루프 · 메타 자기수정까지 5단계 자율 진화 체계를 구축한 프로젝트입니다.

---

## 왜 이 프로젝트를 만들었는가

기존 AI 코딩 에이전트는:
- **비싸다** — Anthropic/OpenAI 유료 API에 종속
- **학습하지 않는다** — 매 세션이 백지에서 시작
- **진화하지 않는다** — 한 번 만든 스킬이 영원히 그대로

Free Claw Code는 이 세 가지를 동시에 해결합니다:
- **완전 무료**: OpenRouter/Groq/z.ai/Cerebras 무료 티어 + Ollama/LM Studio 로컬 모델만 사용
- **기억**: 모든 세션의 결정·실수·패턴이 mempalace에 보존되어 다음 세션에서 자동 회상
- **자가진화**: OpenSpace 엔진이 스킬을 자동 수정·파생·캡처하고, HyperAgent가 진화 메커니즘 자체를 최적화

## 5-Phase 아키텍처

```
┌──────────────────────────────────────────────────┐
│ P4. HyperAgent 메타 자기수정                      │
│     진화 정책·프롬프트·임계값을 자동 편집          │
├──────────────────────────────────────────────────┤
│ P3. Hermes 학습 루프                              │
│     실시간 넛지 · 배치 분석 · 인사이트 · 궤적 압축 │
├──────────────────────────────────────────────────┤
│ P2. OpenSpace 스킬 자가진화                       │
│     FIX/DERIVED/CAPTURED 3모드 · 3종 트리거       │
├──────────────────────────────────────────────────┤
│ P1. Mempalace 초장기 기억                         │
│     세션 wake-up · 자동 마이닝 · idle 마이닝       │
├──────────────────────────────────────────────────┤
│ P0. 무료 LLM 라우터 & 예산 레이어                  │
│     6 provider · 폴백 체인 · 쿼터 관리 · 텔레메트리 │
└──────────────────────────────────────────────────┘
│          claw CLI (Rust) — 40+ 도구               │
└──────────────────────────────────────────────────┘
```

| Phase | 역할 | 핵심 기술 |
|---|---|---|
| **P0** | 무료 모델 라우팅 + 쿼터 관리 + OTel 텔레메트리 | Python 사이드카 (FastAPI), 6 provider YAML 카탈로그, SQLite |
| **P1** | 세션 간 초장기 기억 | [mempalace](https://github.com/milla-jovovich/mempalace) (ChromaDB, 96.6% R@5) |
| **P2** | 스킬 자가진화 | [OpenSpace](https://github.com/HKUDS/OpenSpace) skill_engine (벤더링) |
| **P3** | 에이전트 능동 학습 | 룰 기반 넛지 + 5턴 배치 LLM 분석 + 인사이트 + 궤적 압축 |
| **P4** | 메타 자기수정 | HyperAgent 패턴: 편집 후보 축적 → 합의 → PR 리뷰 → 자동 롤백 |

## 빠른 시작

### 1. 빌드

```bash
git clone https://github.com/kwanghan-bae/free-claw-code
cd free-claw-code/rust
cargo build --workspace
```

### 2. 사이드카 설치

```bash
cd free-claw-code/free-claw-router
uv sync --extra dev
```

### 3. API 키 설정

```bash
# 하나 이상의 무료 provider 키가 필요합니다
export OPENROUTER_API_KEY="sk-or-..."   # openrouter.ai 무료
export GROQ_API_KEY="gsk_..."           # console.groq.com 무료
export ZAI_API_KEY="..."                # z.ai 무료
# Ollama/LM Studio는 로컬이라 키 불필요
```

### 4. mempalace 초기화

```bash
pip install mempalace
mempalace init ~/projects
```

### 5. 실행

```bash
# 터미널 1: 사이드카 시작
cd free-claw-router
uv run uvicorn router.server.openai_compat:app --port 7801

# 터미널 2: claw 실행
OPENAI_BASE_URL=http://127.0.0.1:7801 ./rust/target/debug/claw prompt "안녕하세요"
```

### 6. 상태 확인

```bash
./rust/target/debug/claw doctor
# router: ok (catalog 2026-04-15) ← 사이드카 연결 확인
```

## 지원 무료 Provider

| Provider | 모델 예시 | 특징 |
|---|---|---|
| [OpenRouter](https://openrouter.ai) | GLM-4.6, DeepSeek-V3 | 가장 넓은 무료 카탈로그 |
| [Groq](https://groq.com) | Llama-3.3-70b, QwQ-32b | 가장 빠른 추론 |
| [z.ai](https://z.ai) | GLM-4-Flash | 128K 컨텍스트, 높은 무료 쿼터 |
| [Cerebras](https://cerebras.ai) | Llama-3.3-70b, Qwen-Coder-32b | 초저지연 |
| [Ollama](https://ollama.com) | 로컬 모델 | 오프라인, 무제한 |
| [LM Studio](https://lmstudio.ai) | 로컬 모델 | GUI, 오프라인 |

카탈로그는 **자율 PR 루프**로 자동 갱신됩니다: claw CronCreate → 리서치 에이전트 → 워크트리 → gh PR → Claude 리뷰 → 사람 승인.

## 사이드카 구조

```
free-claw-router/
├── router/
│   ├── server/          # FastAPI: /v1/chat/completions, /health, /cron
│   ├── catalog/         # 6 provider YAML + hot-reload + 자율 갱신
│   ├── routing/         # 정책 기반 폴백 체인 + 태스크 힌트 분류
│   ├── dispatch/        # httpx 디스패치 + SSE 릴레이 + 폴백
│   ├── quota/           # 글로벌 예약 버킷 + 백프레셔
│   ├── telemetry/       # SQLite: traces/spans/events/evaluations
│   ├── adapters/        # Hermes credential/ratelimit 포팅
│   ├── memory/          # P1: wake-up 주입, 자동 마이닝, idle 감지
│   ├── skills/          # P2: OpenSpace bridge, 분석기 훅, 진화 트리거
│   ├── learning/        # P3: 넛지 엔진, 인사이트, 궤적 압축
│   ├── meta/            # P4: 메타 분석, 합의, 편집, 평가, 롤백
│   └── vendor/
│       └── openspace_engine/  # OpenSpace skill_engine 벤더링 + shim
```

## 문서

| 문서 | 설명 |
|---|---|
| [USAGE.md](./USAGE.md) | 빌드, 인증, CLI, 세션, 패리티 워크플로우 |
| [PARITY.md](./PARITY.md) | Rust 포트 패리티 상태 |
| [ROADMAP.md](./ROADMAP.md) | 활성 로드맵 |
| [rust/README.md](./rust/README.md) | 크레이트 맵, CLI, 워크스페이스 |

### 설계 문서 (specs)

| Phase | 설계 |
|---|---|
| P0 | [무료 LLM 라우터 설계](./docs/superpowers/specs/2026-04-15-p0-free-llm-router-design.md) |
| P1 | [Mempalace 기억 설계](./docs/superpowers/specs/2026-04-16-p1-mempalace-memory-design.md) |
| P2 | [OpenSpace 스킬 진화 설계](./docs/superpowers/specs/2026-04-16-p2-openspace-skill-evolution-design.md) |
| P3 | [Hermes 학습 루프 설계](./docs/superpowers/specs/2026-04-16-p3-hermes-learning-loop-design.md) |
| P4 | [HyperAgent 메타 진화 설계](./docs/superpowers/specs/2026-04-17-p4-hyperagent-meta-evolution-design.md) |

## 기반 프로젝트

이 프로젝트는 다음 오픈소스의 구조와 아이디어를 활용합니다:

- [ultraworkers/claw-code](https://github.com/ultraworkers/claw-code) — Rust CLI 에이전트 하네스 (포크 원본)
- [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) — 자율 학습 루프, 메모리 넛지 패턴
- [HKUDS/OpenSpace](https://github.com/HKUDS/OpenSpace) — 스킬 자가진화 엔진
- [MemPalace/mempalace](https://github.com/milla-jovovich/mempalace) — ChromaDB 기반 초장기 기억
- [Meta HyperAgents (arXiv 2603.19461)](https://arxiv.org/abs/2603.19461) — 메타인지 자기수정 논문

## 면책

- 이 저장소는 원본 Claude Code 소스의 소유권을 주장하지 않습니다.
- 이 저장소는 Anthropic과 **제휴, 보증, 유지보수 관계가 없습니다**.
- 이 프로젝트는 개인 학습 및 연구 목적입니다.

## 라이선스

원본 claw-code 라이선스를 따릅니다.
