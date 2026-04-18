# Claw Code Usage

This guide covers the current Rust workspace under `rust/` and the `claw` CLI binary. If you are brand new, make the doctor health check your first run: start `claw`, then run `/doctor`.

## Quick-start health check

Run this before prompts, sessions, or automation:

```bash
cd rust
cargo build --workspace
./target/debug/claw
# first command inside the REPL
/doctor
```

`/doctor` is the built-in setup and preflight diagnostic. Once you have a saved session, you can rerun it with `./target/debug/claw --resume latest /doctor`.

## Prerequisites

- Rust toolchain with `cargo`
- One of:
  - `ANTHROPIC_API_KEY` for direct API access
  - `ANTHROPIC_AUTH_TOKEN` for bearer-token auth
- Optional: `ANTHROPIC_BASE_URL` when targeting a proxy or local service

## Install / build the workspace

```bash
cd rust
cargo build --workspace
```

The CLI binary is available at `rust/target/debug/claw` after a debug build. Make the doctor check above your first post-build step.

## Quick start

### First-run doctor check

```bash
cd rust
./target/debug/claw
/doctor
```

### Interactive REPL

```bash
cd rust
./target/debug/claw
```

### One-shot prompt

```bash
cd rust
./target/debug/claw prompt "summarize this repository"
```

### Shorthand prompt mode

```bash
cd rust
./target/debug/claw "explain rust/crates/runtime/src/lib.rs"
```

### JSON output for scripting

```bash
cd rust
./target/debug/claw --output-format json prompt "status"
```

## Model and permission controls

```bash
cd rust
./target/debug/claw --model sonnet prompt "review this diff"
./target/debug/claw --permission-mode read-only prompt "summarize Cargo.toml"
./target/debug/claw --permission-mode workspace-write prompt "update README.md"
./target/debug/claw --allowedTools read,glob "inspect the runtime crate"
```

Supported permission modes:

- `read-only`
- `workspace-write`
- `danger-full-access`

Model aliases currently supported by the CLI:

- `opus` → `claude-opus-4-6`
- `sonnet` → `claude-sonnet-4-6`
- `haiku` → `claude-haiku-4-5-20251213`

## Authentication

### API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### OAuth

```bash
cd rust
export ANTHROPIC_AUTH_TOKEN="anthropic-oauth-or-proxy-bearer-token"
```

### Which env var goes where

`claw` accepts two Anthropic credential env vars and they are **not interchangeable** — the HTTP header Anthropic expects differs per credential shape. Putting the wrong value in the wrong slot is the most common 401 we see.

| Credential shape | Env var | HTTP header | Typical source |
|---|---|---|---|
| `sk-ant-*` API key | `ANTHROPIC_API_KEY` | `x-api-key: sk-ant-...` | [console.anthropic.com](https://console.anthropic.com) |
| OAuth access token (opaque) | `ANTHROPIC_AUTH_TOKEN` | `Authorization: Bearer ...` | an Anthropic-compatible proxy or OAuth flow that mints bearer tokens |
| OpenRouter key (`sk-or-v1-*`) | `OPENAI_API_KEY` + `OPENAI_BASE_URL=https://openrouter.ai/api/v1` | `Authorization: Bearer ...` | [openrouter.ai/keys](https://openrouter.ai/keys) |

**Why this matters:** if you paste an `sk-ant-*` key into `ANTHROPIC_AUTH_TOKEN`, Anthropic's API will return `401 Invalid bearer token` because `sk-ant-*` keys are rejected over the Bearer header. The fix is a one-line env var swap — move the key to `ANTHROPIC_API_KEY`. Recent `claw` builds detect this exact shape (401 + `sk-ant-*` in the Bearer slot) and append a hint to the error message pointing at the fix.

**If you meant a different provider:** if `claw` reports missing Anthropic credentials but you already have `OPENAI_API_KEY`, `XAI_API_KEY`, or `DASHSCOPE_API_KEY` exported, you most likely forgot to prefix the model name with the provider's routing prefix. Use `--model openai/gpt-4.1-mini` (OpenAI-compat / OpenRouter / Ollama), `--model grok` (xAI), or `--model qwen-plus` (DashScope) and the prefix router will select the right backend regardless of the ambient credentials. The error message now includes a hint that names the detected env var.

## Local Models

`claw` can talk to local servers and provider gateways through either Anthropic-compatible or OpenAI-compatible endpoints. Use `ANTHROPIC_BASE_URL` with `ANTHROPIC_AUTH_TOKEN` for Anthropic-compatible services, or `OPENAI_BASE_URL` with `OPENAI_API_KEY` for OpenAI-compatible services.

### Anthropic-compatible endpoint

```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:8080"
export ANTHROPIC_AUTH_TOKEN="local-dev-token"

cd rust
./target/debug/claw --model "claude-sonnet-4-6" prompt "reply with the word ready"
```

### OpenAI-compatible endpoint

```bash
export OPENAI_BASE_URL="http://127.0.0.1:8000/v1"
export OPENAI_API_KEY="local-dev-token"

cd rust
./target/debug/claw --model "qwen2.5-coder" prompt "reply with the word ready"
```

### Ollama

```bash
export OPENAI_BASE_URL="http://127.0.0.1:11434/v1"
unset OPENAI_API_KEY

cd rust
./target/debug/claw --model "llama3.2" prompt "summarize this repository in one sentence"
```

### OpenRouter

```bash
export OPENAI_BASE_URL="https://openrouter.ai/api/v1"
export OPENAI_API_KEY="sk-or-v1-..."

cd rust
./target/debug/claw --model "openai/gpt-4.1-mini" prompt "summarize this repository in one sentence"
```

### Alibaba DashScope (Qwen)

For Qwen models via Alibaba's native DashScope API (higher rate limits than OpenRouter):

```bash
export DASHSCOPE_API_KEY="sk-..."

cd rust
./target/debug/claw --model "qwen/qwen-max" prompt "hello"
# or bare:
./target/debug/claw --model "qwen-plus" prompt "hello"
```

Model names starting with `qwen/` or `qwen-` are automatically routed to the DashScope compatible-mode endpoint (`https://dashscope.aliyuncs.com/compatible-mode/v1`). You do **not** need to set `OPENAI_BASE_URL` or unset `ANTHROPIC_API_KEY` — the model prefix wins over the ambient credential sniffer.

Reasoning variants (`qwen-qwq-*`, `qwq-*`, `*-thinking`) automatically strip `temperature`/`top_p`/`frequency_penalty`/`presence_penalty` before the request hits the wire (these params are rejected by reasoning models).

## Supported Providers & Models

`claw` has three built-in provider backends. The provider is selected automatically based on the model name, falling back to whichever credential is present in the environment.

### Provider matrix

| Provider | Protocol | Auth env var(s) | Base URL env var | Default base URL |
|---|---|---|---|---|
| **Anthropic** (direct) | Anthropic Messages API | `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` | `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` |
| **xAI** | OpenAI-compatible | `XAI_API_KEY` | `XAI_BASE_URL` | `https://api.x.ai/v1` |
| **OpenAI-compatible** | OpenAI Chat Completions | `OPENAI_API_KEY` | `OPENAI_BASE_URL` | `https://api.openai.com/v1` |
| **DashScope** (Alibaba) | OpenAI-compatible | `DASHSCOPE_API_KEY` | `DASHSCOPE_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |

The OpenAI-compatible backend also serves as the gateway for **OpenRouter**, **Ollama**, and any other service that speaks the OpenAI `/v1/chat/completions` wire format — just point `OPENAI_BASE_URL` at the service.

**Model-name prefix routing:** If a model name starts with `openai/`, `gpt-`, `qwen/`, or `qwen-`, the provider is selected by the prefix regardless of which env vars are set. This prevents accidental misrouting to Anthropic when multiple credentials exist in the environment.

### Tested models and aliases

These are the models registered in the built-in alias table with known token limits:

| Alias | Resolved model name | Provider | Max output tokens | Context window |
|---|---|---|---|---|
| `opus` | `claude-opus-4-6` | Anthropic | 32 000 | 200 000 |
| `sonnet` | `claude-sonnet-4-6` | Anthropic | 64 000 | 200 000 |
| `haiku` | `claude-haiku-4-5-20251213` | Anthropic | 64 000 | 200 000 |
| `grok` / `grok-3` | `grok-3` | xAI | 64 000 | 131 072 |
| `grok-mini` / `grok-3-mini` | `grok-3-mini` | xAI | 64 000 | 131 072 |
| `grok-2` | `grok-2` | xAI | — | — |

Any model name that does not match an alias is passed through verbatim. This is how you use OpenRouter model slugs (`openai/gpt-4.1-mini`), Ollama tags (`llama3.2`), or full Anthropic model IDs (`claude-sonnet-4-20250514`).

### User-defined aliases

You can add custom aliases in any settings file (`~/.claw/settings.json`, `.claw/settings.json`, or `.claw/settings.local.json`):

```json
{
  "aliases": {
    "fast": "claude-haiku-4-5-20251213",
    "smart": "claude-opus-4-6",
    "cheap": "grok-3-mini"
  }
}
```

Local project settings override user-level settings. Aliases resolve through the built-in table, so `"fast": "haiku"` also works.

### How provider detection works

1. If the resolved model name starts with `claude` → Anthropic.
2. If it starts with `grok` → xAI.
3. Otherwise, `claw` checks which credential is set: `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` first, then `OPENAI_API_KEY`, then `XAI_API_KEY`.
4. If nothing matches, it defaults to Anthropic.

## FAQ

### What about Codex?

The name "codex" appears in the Claw Code ecosystem but it does **not** refer to OpenAI Codex (the code-generation model). Here is what it means in this project:

- **`oh-my-codex` (OmX)** is the workflow and plugin layer that sits on top of `claw`. It provides planning modes, parallel multi-agent execution, notification routing, and other automation features. See [PHILOSOPHY.md](./PHILOSOPHY.md) and the [oh-my-codex repo](https://github.com/Yeachan-Heo/oh-my-codex).
- **`.codex/` directories** (e.g. `.codex/skills`, `.codex/agents`, `.codex/commands`) are legacy lookup paths that `claw` still scans alongside the primary `.claw/` directories.
- **`CODEX_HOME`** is an optional environment variable that points to a custom root for user-level skill and command lookups.

`claw` does **not** support OpenAI Codex sessions, the Codex CLI, or Codex session import/export. If you need to use OpenAI models (like GPT-4.1), configure the OpenAI-compatible provider as shown above in the [OpenAI-compatible endpoint](#openai-compatible-endpoint) and [OpenRouter](#openrouter) sections.

## HTTP proxy support

`claw` honours the standard `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` environment variables (both upper- and lower-case spellings are accepted) when issuing outbound requests to Anthropic, OpenAI-, and xAI-compatible endpoints. Set them before launching the CLI and the underlying `reqwest` client will be configured automatically.

### Environment variables

```bash
export HTTPS_PROXY="http://proxy.corp.example:3128"
export HTTP_PROXY="http://proxy.corp.example:3128"
export NO_PROXY="localhost,127.0.0.1,.corp.example"

cd rust
./target/debug/claw prompt "hello via the corporate proxy"
```

### Programmatic `proxy_url` config option

As an alternative to per-scheme environment variables, the `ProxyConfig` type exposes a `proxy_url` field that acts as a single catch-all proxy for both HTTP and HTTPS traffic. When `proxy_url` is set it takes precedence over the separate `http_proxy` and `https_proxy` fields.

```rust
use api::{build_http_client_with, ProxyConfig};

// From a single unified URL (config file, CLI flag, etc.)
let config = ProxyConfig::from_proxy_url("http://proxy.corp.example:3128");
let client = build_http_client_with(&config).expect("proxy client");

// Or set the field directly alongside NO_PROXY
let config = ProxyConfig {
    proxy_url: Some("http://proxy.corp.example:3128".to_string()),
    no_proxy: Some("localhost,127.0.0.1".to_string()),
    ..ProxyConfig::default()
};
let client = build_http_client_with(&config).expect("proxy client");
```

### Notes

- When both `HTTPS_PROXY` and `HTTP_PROXY` are set, the secure proxy applies to `https://` URLs and the plain proxy applies to `http://` URLs.
- `proxy_url` is a unified alternative: when set, it applies to both `http://` and `https://` destinations, overriding the per-scheme fields.
- `NO_PROXY` accepts a comma-separated list of host suffixes (for example `.corp.example`) and IP literals.
- Empty values are treated as unset, so leaving `HTTPS_PROXY=""` in your shell will not enable a proxy.
- If a proxy URL cannot be parsed, `claw` falls back to a direct (no-proxy) client so existing workflows keep working; double-check the URL if you expected the request to be tunnelled.

## Common operational commands

```bash
cd rust
./target/debug/claw status
./target/debug/claw sandbox
./target/debug/claw agents
./target/debug/claw mcp
./target/debug/claw skills
./target/debug/claw system-prompt --cwd .. --date 2026-04-04
```

## Session management

REPL turns are persisted under `.claw/sessions/` in the current workspace.

```bash
cd rust
./target/debug/claw --resume latest
./target/debug/claw --resume latest /status /diff
```

Useful interactive commands include `/help`, `/status`, `/cost`, `/config`, `/session`, `/model`, `/permissions`, and `/export`.

## Config file resolution order

Runtime config is loaded in this order, with later entries overriding earlier ones:

1. `~/.claw.json`
2. `~/.config/claw/settings.json`
3. `<repo>/.claw.json`
4. `<repo>/.claw/settings.json`
5. `<repo>/.claw/settings.local.json`

## Mock parity harness

The workspace includes a deterministic Anthropic-compatible mock service and parity harness.

```bash
cd rust
./scripts/run_mock_parity_harness.sh
```

Manual mock service startup:

```bash
cd rust
cargo run -p mock-anthropic-service -- --bind 127.0.0.1:0
```

## Verification

```bash
cd rust
cargo test --workspace
```

## Dogfood 운영 가이드 (P5 L2)

P5 L2 완료 후 1주 실사용 검증 단계.

### 사전 준비

1. `.env`에 필수 키 4개 입력:
   - `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `ZAI_API_KEY`, `CEREBRAS_API_KEY`
   - 선택: `ANTHROPIC_API_KEY` (Claude review 워크플로용)
2. `./scripts/bootstrap-dogfood.sh` — 7단계 환경 점검. 실패 단계 안내대로 보정 후 재실행.
3. 사이드카 기동 (부트스트랩이 기동시키지 않은 경우):
   ```
   cd free-claw-router && uv run uvicorn router.server.openai_compat:app --port 7801
   ```
   (또는 부트스트랩 `--restart` 플래그)
4. 현재 쉘에서 `export OPENAI_BASE_URL=http://127.0.0.1:7801` — claw가 이 URL로 요청 라우팅.

### Day 1~7 리듬

| 일자 | 활동 | 확인 지표 |
|---|---|---|
| Day 1 | 첫 세션 3회 (간단 리팩토링 수준) | 실패율 < 10%, TTFT 측정, 기본 텔레메트리 수집 |
| Day 2~3 | 실사용 3~5세션/일 (P5 자체 작업에 claw 사용) | `skill_model_affinity` ≥ 3×3 (skill, model) 쌍 |
| Day 4 | mempalace 조회 + P3 궤적 압축 확인 | `insights` ≥ 1건 |
| Day 5 | 메타 분석 강제 트리거 (dev mode) | `suggestions` ≥ 3건 |
| Day 6 | 일일 03:00 UTC 크론 대기 → 메타 PR 관찰 | PR ≥ 1건, Claude review `REQUEST_CHANGES` 없음 |
| Day 7 | `/meta report` 감사 + 판정 체크리스트 | 스냅샷 작성, P6 입력 자료 |

매일 끝에 `./scripts/dogfood-snapshot.sh` 실행 → `docs/superpowers/dogfood/YYYY-MM-DD/` 아카이브.

### 수동 트리거 (개발자 편의)

`FCR_DEV_TRIGGERS=1` 환경변수 설정 후 사이드카 기동 시 활성화:

```bash
# P4 파이프라인 상태 점검
curl http://127.0.0.1:7801/healthz/pipeline

# 현재 open 궤적 분석 즉시 실행
curl -X POST http://127.0.0.1:7801/meta/analyze-now

# 편집 제안 즉시 빌드 (일일 크론 우회)
curl -X POST http://127.0.0.1:7801/meta/evolve-now

# skill_model_affinity 재계산 (읽기 모델이므로 실질 no-op)
curl -X POST http://127.0.0.1:7801/telemetry/readmodel/refresh
```

플래그 없으면 404 반환 — 프로덕션 경로 노출 위험 없음.

### Day 7 판정 체크리스트

P6 착수 전 **모두** 충족 확인:

- [ ] 세션 실패율 < 10% (최근 7일)
- [ ] OpenRouter p50 TTFT < 1.5s (SSE 적용 시)
- [ ] `skill_model_affinity` (skill, model) 쌍 ≥ 10
- [ ] affinity 보너스가 라우팅 결정 1건 이상 뒤집음 (events 조회로 검증)
- [ ] P3 `insights` ≥ 3건
- [ ] `meta_suggestions.json` ≥ 5건 누적
- [ ] 메타 편집 PR ≥ 1건 자동 생성 + Claude review `REQUEST_CHANGES` 없음
- [ ] `/meta/report`가 24h 활동을 공백 없이 렌더
- [ ] `clawd meta report` 명령이 에러 없이 HTML 오픈
- [ ] GC 크론 1회 이상 실행 + `gc_run` 이벤트 기록
- [ ] `cargo test --workspace` 통과 유지 (flaky 기준 제외), `pytest` 통과 유지

### 미충족 시

1건이라도 ❌면 원인을 `docs/superpowers/dogfood/p5-blockers.md`에 기록.
수정 스프린트(가변 기간) 후 재측정. P6 스펙은 Day 7 회고 문서(`p5-retrospective.md`)를 필수 입력으로 받음 — 회고 없이 P6 브레인스토밍 호출 금지.

### affinity 헤더 활용

claw/Rust 클라이언트가 `X-Skill-ID: <skill>` 헤더를 보내야 affinity 보너스가 발화합니다. 헤더 없으면 cold-start(보너스 0)로 동작 — 라우팅은 정적 정책만으로 결정. Rust CLI 쪽에서 스킬 기반 요청 시 헤더를 자동 주입하는 것은 P6 작업.

## Workspace overview

Current Rust crates:

- `api`
- `commands`
- `compat-harness`
- `mock-anthropic-service`
- `plugins`
- `runtime`
- `rusty-claude-cli`
- `telemetry`
- `tools`
