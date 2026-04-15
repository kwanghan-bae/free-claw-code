# P0 — Free LLM Router & Budget Layer (Design)

- **Date:** 2026-04-15
- **Status:** Draft — awaiting user review
- **Owner:** kwanghan-bae
- **Parent program:** free-claw-code self-evolving coding agent (5-phase plan: P0 → P4)
- **Follow-ups this spec enables:** P1 (Memplace), P2 (OpenSpace), P3 (Hermes), P4 (HyperAgent)

## 1. Context

`free-claw-code` is a fork of `ultraworkers/claw-code` that the owner intends to evolve into a personally-tuned coding agent with five layered subsystems: free-only LLM routing (P0), ultra-long memory via Memplace (P1), skill self-evolution via OpenSpace (P2), Hermes-style in-agent learning (P3), and a HyperAgent-style meta-self-modification layer on top (P4).

This spec covers **only P0**. P0 is the foundation: without a reliable, observable, concurrency-safe, free-only model access layer, none of P1–P4 can produce useful signal. P0 also has to pre-declare the data contracts that P2–P4 will consume, because redoing those later would force rewrites in all three downstream subsystems.

The owner's operational profile: **β — cloud-free-tier heavy** (OpenRouter/z.ai/Groq/Cerebras free models as primary, local Ollama/LM Studio as fallback), frequent parallel sub-agent workloads, and a commitment to building an autonomous self-maintenance loop on top of `gh` and git worktrees.

## 2. Scope

### In scope (P0)

1. **OpenAI-compatible router sidecar** — a long-running Python process that claw's Rust `api` crate talks to via `OPENAI_BASE_URL`. All outbound LLM traffic flows through it.
2. **Living model catalog** — per-provider YAML resource files in `catalog/data/`, kept fresh through a producer/tester/reviewer/human PR loop driven by claw itself.
3. **L1+L4 hybrid routing policy** — static priority lists as the floor, learned per-(model × task × skill) scoring layered on top. Skill-model affinity is surfaced as a first-class concept.
4. **Global quota reservation bucket** — rate-limit tracking that parallel sub-agents share; back-pressure signal back to claw when quotas thin.
5. **OpenTelemetry-style span hierarchy** (telemetry Shape C) — traces/spans/events/evaluations in SQLite, with forward-compat to OTLP.
6. **Hermes routing substrate absorption** — `credential_pool.py`, `rate_limit_tracker.py`, `smart_model_routing.py`, `auxiliary_client.py` pulled in via `git subtree` + a thin adapter layer.
7. **Autonomous PR loop** — claw's Cron tool schedules a research agent that opens catalog-refresh PRs; a high-end Claude Code reviewer auto-comments on every new PR; the human approves and merges.
8. **Hot-reload** — catalog and policy updates take effect without restarting the sidecar.

### Out of scope (deferred)

- **Skill DAG storage with model-axis extension** — P0 emits the affinity signal; P2 (OpenSpace) stores and consumes it.
- **Agent-curated memory & in-session learning loop** — P3 (Hermes absorption).
- **Meta-evolution of the routing policy itself** — P4 (HyperAgent). P0 exposes `policy.yaml` and telemetry in an HyperAgent-editable shape, but does not attempt self-modification.
- **Distributed OTLP export** — P0 writes the same span model to SQLite. OTLP emitter is a later swap.
- **Adaptive routing (L4 online learning loop)** — P0 provides the data substrate and a static scorer stub. Active online learning comes after P3.
- **Non-free providers** — Anthropic/OpenAI paid models are disallowed at the router level (filtered by `free: true` in catalog).

### Explicit non-goals

- Do not attempt parity with Hermes's full feature set (messaging gateways, skill TUI, etc.). P0 absorbs only the routing/credential/rate-limit subsystem.
- Do not couple to any single provider's proprietary features (e.g., Groq structured output must degrade gracefully if the next-ranked provider is plain OpenAI-compat).

## 3. Architecture

### 3.1 Process topology

```
┌──────────────────────────────────────────────────────────────────┐
│  free-claw-code repo                                              │
│                                                                   │
│  ┌────────────────────────┐        ┌────────────────────────────┐ │
│  │  claw CLI (Rust)       │  HTTP  │  free-claw-router (Python) │ │
│  │  rust/crates/...       │ <────> │  sidecar, long-running     │ │
│  │                        │        │                             │ │
│  │  OPENAI_BASE_URL =     │        │  OpenAI-compat server       │ │
│  │  http://127.0.0.1:7801 │        │  Catalog · Router · Quota  │ │
│  │                        │        │  Dispatch · Telemetry       │ │
│  │  telemetry crate       │        │  APScheduler (workers)      │ │
│  │  emits spans  ─────────┼──JSONL─┤> tail → SQLite + evals     │ │
│  └────────────────────────┘        └────────────────────────────┘ │
│                                              │                    │
│                                              │ spawns via         │
│                                              ▼ Task tool          │
│                                     ┌────────────────────┐        │
│                                     │ research agent     │        │
│                                     │ (claw sub-agent)   │        │
│                                     │ runs in git worktree│       │
│                                     │ opens gh PR        │        │
│                                     └────────────────────┘        │
└──────────────────────────────────────────────────────────────────┘
                        │
                        │ gh pr create
                        ▼
        ┌──────────────────────────────────┐
        │ GitHub                           │
        │  .github/workflows/              │
        │     catalog-refresh-verify.yml  │
        │     claude-review.yml           │
        └──────────────────────────────────┘
```

### 3.2 Module layout

```
free-claw-router/                       # NEW subdir in this repo
├── pyproject.toml
├── uv.lock
├── README.md
├── router/
│   ├── __init__.py
│   ├── server/
│   │   ├── openai_compat.py            # FastAPI app: /v1/chat/completions, /v1/models, /health
│   │   ├── schemas.py                  # request/response pydantic models
│   │   └── lifespan.py                 # startup/shutdown, catalog warmup
│   ├── catalog/
│   │   ├── registry.py                 # load, search, validate catalog
│   │   ├── schema.py                   # ModelSpec, ProviderSpec, Capabilities, FreeTier
│   │   ├── data/                       # <-- resource files
│   │   │   ├── openrouter.yaml
│   │   │   ├── zai.yaml
│   │   │   ├── groq.yaml
│   │   │   ├── cerebras.yaml
│   │   │   ├── ollama.yaml
│   │   │   └── lmstudio.yaml
│   │   ├── refresh/
│   │   │   ├── scheduler.py            # registered via claw CronCreate
│   │   │   ├── producer.py             # orchestrates a research agent run
│   │   │   ├── worktree.py             # wraps git worktree add/remove
│   │   │   └── pr.py                   # wraps gh pr create/comment
│   │   └── hot_reload.py               # watchdog → atomic swap, double-buffered
│   ├── routing/
│   │   ├── decide.py                   # candidate filter + rank + fallback chain
│   │   ├── score.py                    # per-(model, task, skill) learned score
│   │   ├── policy.yaml                 # initial priorities — HyperAgent-editable
│   │   └── hints.py                    # task_type inference from request payload
│   ├── quota/
│   │   ├── bucket.py                   # global reservation, async lock
│   │   ├── headers.py                  # x-ratelimit-* parser (from Hermes)
│   │   ├── predict.py                  # can-afford check pre-dispatch
│   │   └── backpressure.py             # notifies claw via HTTP when tight
│   ├── dispatch/
│   │   ├── client.py                   # http call; wraps credential_pool
│   │   ├── sse_relay.py                # streaming proxy, preserves back-pressure
│   │   └── fallback.py                 # 429/5xx → next candidate
│   ├── telemetry/
│   │   ├── spans.py                    # Trace, Span, SpanKind, W3C traceparent
│   │   ├── events.py                   # typed event variants
│   │   ├── evaluations.py              # per-span scored evaluations
│   │   ├── store.py                    # SQLite schema, write path
│   │   ├── ingest_jsonl.py             # tail claw's JSONL sink → spans table
│   │   └── readmodels.py               # query-side materialized views
│   ├── skill_affinity/
│   │   ├── events.py                   # emit per-(skill, model, outcome) signals
│   │   └── bridge.py                   # expose a read endpoint for P2 (OpenSpace)
│   ├── vendor/                         # git subtree roots
│   │   └── hermes/                     # pulled from NousResearch/hermes-agent
│   └── adapters/
│       ├── hermes_credentials.py       # vendor/hermes → router.dispatch
│       ├── hermes_ratelimit.py         # vendor/hermes → router.quota
│       └── hermes_routing.py           # smart_model_routing → router.routing.hints
├── tests/
│   ├── test_server.py
│   ├── test_catalog.py
│   ├── test_routing.py
│   ├── test_quota.py
│   ├── test_telemetry.py
│   └── live_smoke/                     # skipped unless PROVIDER keys set
│       └── test_openrouter.py
└── ops/
    ├── claude-review-prompt.md         # used by .github/workflows/claude-review.yml
    ├── catalog-schema.json             # JSON Schema for research-agent output
    └── .env.example
```

Existing claw assets we **extend, not replace**:

- `rust/crates/api/src/providers/openai_compat.rs` — already handles OpenAI-compatible endpoints; `OPENAI_BASE_URL` already merged (commit `1ecdb10`). No code change required to point claw at the sidecar.
- `rust/crates/telemetry/src/lib.rs` — add span event variants (`SpanStarted`, `SpanEnded`) and `trace_id` + `span_id` fields; keep existing `SessionTracer` surface for back-compat.
- `rust/crates/runtime/src/session.rs` — create a root span per session, propagate trace context to sub-agent spawns.
- `rust/crates/tools/src/lib.rs` — wrap `execute_tool` to open a `tool_call` span; attach model hint when the tool's side-effect is an LLM call.
- `rust/crates/runtime/src/task_registry.rs` — each `Task*` becomes a child span; parent inferred from `parent_session_id`.

### 3.3 Data flow — a single chat completion

```
claw (Rust)
  ├── starts root span for session S
  ├── prompt_builder emits task_type hint
  ├── POST http://127.0.0.1:7801/v1/chat/completions
  │      header: traceparent (W3C) — trace_id + parent_span_id
  │      body:   OpenAI-compat payload
  │              + x-free-claw-hints: { task_type, skill_id?, urgency }
  │
  └── streams response back to user

sidecar:
  ├── [routing.hints]       classify task_type if not provided
  ├── [routing.decide]      candidates = catalog.filter(caps, quota_check)
  │                         ranked = score(candidates, task, skill_id, learned)
  │                         fallback_chain = [top, top2, top3]
  ├── [quota.bucket]        reserve tokens from provider bucket
  │                         if insufficient → try next candidate
  │                         if all tight → emit backpressure to claw
  ├── [dispatch.client]     pick the first candidate, attach auth via
  │                          vendored credential_pool
  ├── [telemetry.spans]     open `llm_call` span with parent traceparent
  ├── [dispatch.sse_relay]  stream response back
  ├── parse x-ratelimit-* → [quota.headers] update bucket
  ├── on 429/5xx          → [dispatch.fallback] retry next candidate
  ├── on terminal success → close span, emit event, record tokens
  └── [skill_affinity.events] if skill_id present, emit signal row
```

### 3.4 Autonomous PR loop — catalog refresh

```
claw CronCreate
  ├── schedule: 0 3 * * *  (daily 03:00 local)
  ├── payload:  "refresh catalog for provider=openrouter"
  │
  ▼
sidecar APScheduler (worker)
  ├── acquire .refresh-lock.openrouter
  ├── git worktree add -b catalog/refresh/2026-04-15-openrouter \
  │       /tmp/free-claw-router-worktrees/openrouter-2026-04-15 main
  │
  ▼
research-agent (spawned via claw Task tool, in the worktree)
  ├── inputs: catalog/data/openrouter.yaml (current)
  │           ops/catalog-schema.json
  │           a prompt with provider docs URLs
  ├── tools:  WebFetch, Read, Edit/Write, Bash
  ├── workflow:
  │     1. fetch https://openrouter.ai/api/v1/models  (public, no auth required)
  │     2. for each free model (price.input==0, price.output==0):
  │          verify via short /v1/chat/completions smoke
  │          capture context_window, tool_use support, quota headers
  │     3. diff against current YAML
  │     4. write new YAML (JSON Schema-validated)
  │     5. cargo/pytest run in worktree
  │     6. gh pr create --title "catalog: refresh openrouter 2026-04-15" \
  │                     --body "<diff summary + evidence URLs>"
  │
  ▼
GitHub
  ├── catalog-refresh-verify.yml runs
  │     - YAML schema validate
  │     - invariants: all entries free==true, context_window>0
  │     - snapshot test: existing routing traces still pass
  │
  ├── claude-review.yml runs (auto — this is β)
  │     - ANTHROPIC_API_KEY secret → Claude Code reviews PR diff + CI output
  │     - posts review via gh pr review --comment
  │     - checklist: ToS compliance, quota realism, quirks captured,
  │                   no secrets, evidence URLs present
  │
  ▼
human (owner)
  ├── approves & merges (the only human step)
  │
  ▼
sidecar watchdog
  ├── sees catalog/data/openrouter.yaml changed
  ├── validates + double-buffer swap
  ├── logs reload event to telemetry
  └── future requests use new catalog
```

## 4. Catalog

### 4.1 Schema (pydantic + JSON Schema)

```yaml
# catalog/data/openrouter.yaml (example, truncated)
provider_id: openrouter
base_url: https://openrouter.ai/api/v1
auth:
  env: OPENROUTER_API_KEY
  scheme: bearer
known_ratelimit_header_schema: openrouter_standard
models:
  - model_id: z-ai/glm-4.6:free
    status: active                 # active|deprecated|experimental
    context_window: 131072
    tool_use: true
    structured_output: partial
    free_tier:
      rpm: 20
      tpm: 100000
      daily: null
      reset_policy: minute
    pricing: { input: 0, output: 0, free: true }
    quirks:
      - "tool_calls field uses OpenAI v2 schema; no arguments_format quirks"
      - "max stream chunk size ~4KB — sse_relay must not buffer > 2KB per flush"
    evidence_urls:
      - https://openrouter.ai/models/z-ai/glm-4.6:free
      - https://openrouter.ai/api/v1/models
    last_verified: 2026-04-15T03:14:02Z
    first_seen: 2026-03-28
```

### 4.2 Invariants (enforced by `catalog/schema.py` + CI)

- `pricing.free == true` for every model (P0 refuses non-free).
- `context_window > 0`, `model_id` globally unique, `evidence_urls` non-empty.
- `last_verified` within 14 days on every merge (else CI fails with "stale").
- Any model marked `deprecated` must carry a `deprecation_reason` and `replaced_by` pointer.

### 4.3 Research-agent output contract

`ops/catalog-schema.json` (strict). The agent emits JSON, not YAML — the sidecar converts to YAML to avoid formatting sins. The reviewer auto-rejects if `evidence_urls` is empty or `last_verified` is missing.

### 4.4 Day-1 provider set (proposed — open to user edit)

| Provider   | Why day-1                                             | Has `/v1/models`? |
|------------|-------------------------------------------------------|--------------------|
| OpenRouter | Broadest free-tier catalog, standardized headers      | yes                |
| z.ai / GLM | Strong reasoning on free tier; Hermes already supports| yes                |
| Groq       | Fastest free-tier inference; tool-use stable          | yes                |
| Cerebras   | Very fast free tier, good for tool-heavy loops        | yes                |
| Ollama     | Local fallback; zero quota pressure                   | yes (local)        |
| LM Studio  | Local fallback; offline CI                            | yes (local)        |

Post-P0 candidates (not day-1): Nous Portal, HuggingFace Inference, Mistral free tier, Together/Fireworks trial credits.

## 5. Routing policy

### 5.1 Static priority (L1 floor)

`routing/policy.yaml` — per task_type, ordered provider:model list + fallback chain. HyperAgent-editable later.

```yaml
# abbreviated
planning:
  priority:
    - openrouter:z-ai/glm-4.6:free
    - openrouter:deepseek/deepseek-v3:free
    - groq:llama-3.3-70b-versatile
    - ollama:qwen2.5-coder:32b
  fallback_any: true   # if all listed are exhausted, fall back to any capable catalog entry
coding:
  priority:
    - groq:llama-3.3-70b-versatile
    - cerebras:qwen-coder-32b-instruct
    - openrouter:z-ai/glm-4.6:free
    - lmstudio:qwen2.5-coder:14b
tool_heavy:
  priority:
    - groq:llama-3.3-70b-versatile
    - openrouter:z-ai/glm-4.6:free
summary: ...
chat: ...
```

### 5.2 Learned scoring (L4 stub at day-1)

`routing/score.py` exposes `score(model_id, task_type, skill_id | None) -> float`. Day-1 implementation returns a prior from the catalog (e.g., `tool_use=true` → +0.2 for `tool_heavy`). Post-P3, it reads `evaluations` table rolling window and applies Thompson sampling. The interface is stable; the body evolves.

### 5.3 Task-type hint flow

Two paths produce the hint:
- **claw-side** — `rust/crates/runtime/src/prompt_builder.rs` emits an `x-free-claw-hints` header. Keyword matching reusing Hermes's `_COMPLEX_KEYWORDS`.
- **router-side** — if header absent, `routing.hints.classify()` runs the same keyword matcher as a fallback.

User override: a slash command `/route coding` pins the hint for the next turn. (claw command registry — Lane 5 exposure.)

## 6. Quota management

### 6.1 Global reservation bucket

`quota/bucket.py` — per `(provider_id, model_id)` pair:

```python
class Bucket:
    rpm_window: deque[float]   # timestamps
    tpm_window: deque[int]     # token amounts
    daily_used: int
    last_reset: datetime
    async def reserve(self, tokens_estimated: int) -> ReservationToken: ...
    async def commit(self, token: ReservationToken, tokens_actual: int) -> None: ...
    async def rollback(self, token: ReservationToken) -> None: ...
```

`asyncio.Lock` per bucket. Parallel sub-agents all `reserve` before dispatch → no over-commit.

### 6.2 Pre-dispatch affordability check

`quota/predict.py` — estimate tokens from request (prompt + `max_tokens`), query bucket, return `sufficient | tight | insufficient`. `tight` still dispatches; `insufficient` skips to next candidate.

### 6.3 Back-pressure to claw

When >80% of all day-1 buckets report `insufficient` for a given task_type, `quota/backpressure.py` POSTs to claw's `/internal/backpressure` with `{task_type, suggested_concurrency}`. claw's subagent spawner (`Agent` tool) honors it — **requires a small claw runtime change** (new listener + concurrency hint plumbing).

## 7. Telemetry (Shape C)

### 7.1 SQLite schema

```sql
-- traces: high-level workflow (e.g., "user turn")
CREATE TABLE traces(
  trace_id BLOB PRIMARY KEY,      -- 16 bytes, W3C
  started_at INTEGER NOT NULL,     -- unix ms
  ended_at INTEGER,
  root_op TEXT NOT NULL,
  root_session_id TEXT,
  catalog_version TEXT NOT NULL,
  policy_version TEXT NOT NULL
);

-- spans: nested units of work
CREATE TABLE spans(
  span_id BLOB PRIMARY KEY,        -- 8 bytes, W3C
  trace_id BLOB NOT NULL REFERENCES traces,
  parent_span_id BLOB,
  op_name TEXT NOT NULL,           -- plan|subagent|llm_call|tool_call|retrieval|...
  model_id TEXT,                   -- nullable; set on llm_call
  provider_id TEXT,
  skill_id TEXT,                   -- nullable
  task_type TEXT,                  -- planning|coding|tool_heavy|...
  started_at INTEGER NOT NULL,
  ended_at INTEGER,
  duration_ms INTEGER,
  status TEXT                      -- ok|io_error|rate_limited|timeout|invalid_response
);
CREATE INDEX idx_spans_model_skill ON spans(model_id, skill_id);
CREATE INDEX idx_spans_task ON spans(task_type, started_at);

-- events: attached facts
CREATE TABLE events(
  event_id INTEGER PRIMARY KEY,
  span_id BLOB NOT NULL REFERENCES spans,
  kind TEXT NOT NULL,              -- http_started|http_succeeded|quota_reserved|retry|...
  payload_json TEXT NOT NULL,
  ts INTEGER NOT NULL
);
CREATE INDEX idx_events_span ON events(span_id);

-- evaluations: scored judgments
CREATE TABLE evaluations(
  id INTEGER PRIMARY KEY,
  span_id BLOB NOT NULL REFERENCES spans,
  evaluator TEXT NOT NULL,         -- rule|claude-reviewer|openspace-engine|hermes-insights|human
  score_dim TEXT NOT NULL,         -- tool_accuracy|output_quality|format_correctness|...
  score_value REAL NOT NULL,       -- 0..1
  rationale TEXT,
  ts INTEGER NOT NULL
);
CREATE INDEX idx_evals_span ON evaluations(span_id);
CREATE INDEX idx_evals_dim ON evaluations(score_dim, ts);
```

### 7.2 claw-side emission (Rust)

- `telemetry` crate adds `SpanStarted { trace_id, span_id, parent_span_id, op_name, attributes }` and `SpanEnded { span_id, status, attributes }` variants.
- Existing `SessionTracer` gets a `start_span(op, attrs) -> SpanGuard` method; guard drops → emit `SpanEnded`.
- W3C traceparent header format: `00-<trace_id(32 hex)>-<span_id(16 hex)>-01`. Emitted by `api` crate on every outbound request to sidecar; ingested by sidecar's `openai_compat` server.

### 7.3 Sidecar-side ingestion

- JSONL sink remains primary write path on claw side (no perf regression).
- `telemetry/ingest_jsonl.py` tails `~/.claude/log/telemetry-*.jsonl` with `watchdog`, parses, writes into SQLite. Ingestion lag target: <500 ms.
- Sidecar-generated spans (routing decisions, quota reservations, fallbacks) written directly to SQLite.

### 7.4 Read-models for downstream consumers

Three materialized views maintained by triggers:

- `skill_model_affinity(skill_id, model_id, trials, success_rate, avg_score_by_dim)` — **the contract to P2.**
- `quota_health(provider_id, model_id, rpm_pressure, tpm_pressure, daily_pressure)` — for P4/HyperAgent.
- `span_cost_rollup(session_id, total_tokens_in, total_tokens_out, wall_ms)` — for user-facing `/usage`.

### 7.5 Evaluator plugin interface

```python
class Evaluator(Protocol):
    evaluator_id: str
    dims: list[str]
    async def evaluate(self, span: Span, events: list[Event]) -> list[Evaluation]: ...
```

Day-1 evaluators: `rule` (syntactic: status codes, retry counts, tool-arg parse success). Others (OpenSpace, Hermes, Claude reviewer, human `/approve`) plug in later without schema change.

## 8. Error handling

- **Provider 429/5xx:** caught in `dispatch.fallback`; retry next candidate up to `max_fallbacks` (default 3). After chain exhaustion, return OpenAI-compat error to claw.
- **Streaming mid-failure:** `sse_relay` emits a clean stream-terminating error chunk to claw; claw surfaces to user; span closed with `status=invalid_response`.
- **Catalog hot-reload failure:** sidecar keeps the old catalog buffer; writes a telemetry alert; refuses to swap until valid.
- **Worktree lock stuck:** scheduler detects >1h lock age → emits alert + auto-releases if no process holds it.
- **PR loop runaway (reviewer rejects 5× in a row):** scheduler halts that provider's refresh for 24h + telemetry alert.
- **Sidecar crash / restart:** in-memory bucket state is lost; rebuild from `events` table's last 5 minutes on boot (fast-forward headers).

## 9. Testing strategy

- **Unit:** every module has `pytest` coverage. Pydantic validation covers schema.
- **Integration:** `tests/live_smoke/` hits real providers when `FREE_CLAW_LIVE=1` and API keys are set. Skipped in default CI.
- **Deterministic routing tests:** `tests/test_routing.py` feeds fixed catalog + fixed task_type → asserts candidate ordering. Fixtures under `tests/fixtures/catalog/`.
- **Quota property tests:** `hypothesis` tests that parallel `reserve`/`commit` never over-commit.
- **Telemetry contract tests:** fixture spans → SQLite → read-model queries match expected shapes.
- **Autonomous PR loop dry-run:** `FREE_CLAW_PR_DRY_RUN=1` short-circuits `gh pr create` to stdout; full loop executable in CI.
- **Reviewer prompt tests:** golden prompts in `ops/` replayed against mock PRs; output validated against a checklist rubric.

## 10. Milestones

| Milestone | Deliverable | Exit criterion |
|-----------|-------------|----------------|
| M0  | Repo scaffold, uv lockfile, FastAPI skeleton, claw points at sidecar | `claw prompt "hi"` goes through sidecar, returns 501 |
| M1  | Catalog schema + 3 provider YAMLs (OpenRouter, Groq, Ollama) + static routing | claw can complete a turn using Groq via sidecar |
| M2  | Credential pool adapter (Hermes subtree) + streaming SSE relay | Streaming response parity with direct provider call |
| M3  | Quota buckets + backpressure endpoint | 5 parallel sub-agents share one free tier without overshoot |
| M4  | Telemetry spans end-to-end (Rust span emit → JSONL → SQLite) | `skill_model_affinity` view returns real rows |
| M5  | Autonomous PR loop (scheduler + research agent + worktree + gh) | Dry-run end-to-end on OpenRouter |
| M6  | Claude Code reviewer action + hot-reload | Live PR merged → sidecar uses new catalog without restart |
| M7  | z.ai, Cerebras, LM Studio YAMLs + quirks | Day-1 provider set complete |

P0 is "done" at M7. P1 brainstorming starts immediately.

## 11. Risks & mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Provider ToS prohibits programmatic scraping of model list | High | `catalog/refresh/producer.py` reads only public endpoints listed in `ops/allowed_sources.yaml`; reviewer prompt cross-checks ToS; refuse unknown sources |
| Free-tier quotas tightened silently | High | Daily `quota_health` view alerts on >20% regression week-over-week |
| Research agent hallucinates a model that does not exist | Medium | Smoke-test step in refresh workflow; reviewer verifies evidence_urls resolve 200; merge-gate |
| Claude reviewer token cost explodes | Medium | Per-PR cap + per-day cap + debounce rule; manual `/review` override if auto path disabled |
| Sidecar crash breaks claw | Medium | claw's `api` crate falls back to direct `OPENAI_BASE_URL=` if sidecar health fails 3× consecutively; `claw doctor` surfaces |
| SQLite contention under parallel load | Low | WAL mode; batched writes; DuckDB upgrade path documented |
| git subtree merge conflicts from Hermes upstream | Medium | Keep adapter layer thin; upstream PRs for any adjustments; monthly subtree pull as a cron task |
| HyperAgent later edits policy.yaml wrongly | High (P4 concern) | `policy.yaml` edits flow through same PR loop; reviewer catches; git history is the rollback path |

## 12. Open questions (to resolve before or during implementation)

- **Q12.1** — Sidecar install path: do we vendor uv into the repo or require the user to have uv globally? *Recommendation: require uv; `install.sh` checks + hints.*
- **Q12.2** — Policy.yaml schema versioning: a field `policy_version: 1` vs a hash-based marker? *Recommendation: semver string; HyperAgent later bumps it.*
- **Q12.3** — Where does the sidecar log? `~/.free-claw-router/` or in-repo `var/`? *Recommendation: `~/.free-claw-router/` to keep repo clean.*
- **Q12.4** — `claw doctor` integration — does it ping sidecar? *Recommendation: yes, add a `RouterHealth` check.*
- **Q12.5** — Should the research agent be restricted to running against one provider per invocation, or can it batch? *Recommendation: one provider per invocation for isolation; scheduler orchestrates.*

## 13. Decisions log (from brainstorm session)

- **D1** — Architecture: B1 (pure Python sidecar, `OPENAI_BASE_URL` swap). *Reason: performance profile is β (cloud-free); sidecar overhead is <0.2%; enables P3/P4 edit-loop.*
- **D2** — Routing level: L1 static floor + L4 adaptive scoring; **no explicit L2 task-hint phase** (hints embedded as router input, scoring subsumes L2). Catalog is a living resource.
- **D3** — Catalog refresh trigger: β + i + y. Auto Claude Code review on every PR; schedule via claw CronCreate (dogfood); research agent performs full autonomous research, not just `/v1/models` scraping.
- **D4** — Telemetry: Shape C (traces/spans/events/evaluations). Day-1 implementation in SQLite; OTLP export deferred.
- **D5** — Skill-model affinity: P0 emits the signal; P2 (OpenSpace) owns the skill DAG with model axis.
- **D6** — Global quota reservation bucket + back-pressure to claw are in P0 scope.
- **D7** — Hermes routing substrate enters via `git subtree` + thin adapter; upstream PRs where changes needed.
- **D8** — Sidecar embeds APScheduler; claw's CronRegistry proxies to it. This unblocks Lane 6's "no real background scheduler" gap and is an upstream-able improvement.

---

**End of design.**
