# P3 — Hermes-Style In-Agent Learning Loop (Design)

- **Date:** 2026-04-16
- **Status:** Draft — awaiting user review
- **Owner:** kwanghan-bae
- **Parent program:** free-claw-code self-evolving coding agent (P0 → P1 → P2 → P3 → P4)
- **Depends on:** P0 (telemetry + dispatch), P1 (mempalace mining pipeline + on_mine_hooks), P2 (OpenSpace skill evolution)
- **Follow-ups:** P4 (HyperAgent meta-self-modification consumes trajectory data)

## 1. Context

P1 and P2 deliver memory and skill evolution, but both are infrastructure-driven — the agent passively receives wake-up context and passively benefits from evolved skills. P3 closes the loop: the agent actively participates in its own learning by saving important decisions, proposing new skills, receiving nudges, and generating cross-session insights.

Inspired by [Hermes Agent](https://github.com/NousResearch/hermes-agent)'s closed learning loop (memory nudges, autonomous skill creation, periodic insights, trajectory compression), adapted for the free-model-only constraint.

## 2. Scope

### In scope

1. **Rule-based nudge detector** — zero-LLM-cost keyword/pattern matcher that flags decisions, lessons, and reusable code patterns in real-time (every turn).
2. **Batch analyzer** — every 5 turns, one LLM call analyzes accumulated conversation for subtler learning opportunities missed by rules.
3. **Nudge cache + injector** — queued nudges inserted into the next request's system message. Agent decides whether to act (MCP calls to mempalace/OpenSpace) or ignore.
4. **Insight generator** — on session close, analyzes the last N sessions (via mempalace search) to produce cross-session pattern reports. Stored in user wing `insights` room.
5. **Trajectory compressor** — on session close, compresses the session into a structured JSON (summary + decisions + mistakes + reusable_patterns + model_performance). Stored in project wing `trajectories` room. P4's primary learning signal.

### Out of scope

- **Hermes full agent architecture** (messaging gateways, personality system, skill TUI) — we take only the learning loop patterns.
- **Fine-tuning data export** — trajectory format is for P4 consumption, not model training.
- **Honcho dialectic user modeling** — deferred; mempalace user wing serves the same purpose for now.
- **Hermes git subtree** — P3 doesn't vendor Hermes code; it reimplements the patterns using our existing P0+P1+P2 infrastructure.

## 3. Architecture

```
per-turn (real-time):
  provider response
    → rule_detector (keyword/pattern, LLM 0)
    → nudge candidates → nudge_cache

every 5 turns:
  accumulated conversation
    → batch_analyzer (LLM 1 call)
    → additional nudge candidates → nudge_cache

next request:
  nudge_cache → nudge_injector → system message prepend
  agent reads nudges → decides to act (MCP) or ignore

session close (P1 on_mine_hooks):
  → insight_generator (LLM 1 call, reads last 5 sessions)
    → mempalace user/insights room
  → trajectory_compressor (LLM 1 call)
    → mempalace project/trajectories room
```

### 3.1 New sidecar modules

```
free-claw-router/router/learning/
├── __init__.py
├── rule_detector.py         # keyword/pattern matching, zero LLM cost
├── batch_analyzer.py        # 5-turn LLM analysis
├── nudge_cache.py           # per-trace nudge queue
├── nudge_injector.py        # system message prepend (like P1 wake-up)
├── insight_generator.py     # cross-session pattern analysis
└── trajectory_compressor.py # session → structured JSON
```

### 3.2 Existing modules touched

| File | Change |
|---|---|
| `router/server/openai_compat.py` | ~6 lines: call rule_detector after dispatch, call nudge_injector before dispatch |
| `router/memory/idle_detector.py` | Register insight_generator + trajectory_compressor as on_mine_hooks |
| `router/server/lifespan.py` | Initialize learning modules |

## 4. Nudge engine

### 4.1 Rule detector (zero cost)

`rule_detector.py` scans each assistant response for patterns:

| Pattern | Nudge type | Example trigger |
|---|---|---|
| `decided to`, `we chose`, `going with` | `memory_save` | "We decided to use GraphQL" |
| `remember that`, `note that`, `important:` | `memory_save` | "Remember that the API rate-limits at 100rpm" |
| Same code block generated 3+ times in session | `skill_create` | Repeated boilerplate extraction candidate |
| `failed because`, `bug was`, `lesson:` | `memory_save` | "The bug was caused by stale cache" |
| 3+ consecutive tool_call failures | `skill_fix` | Tool keeps failing → skill needs repair |

Implementation: regex + counter state per trace. No LLM. Runs in <1ms per response.

### 4.2 Batch analyzer (periodic)

`batch_analyzer.py` — every 5 turns (tracked per trace_id):

1. Collect the last 5 user+assistant turns from the nudge_cache's conversation buffer.
2. One LLM call with system prompt: "Identify learning opportunities: decisions worth saving, patterns worth extracting as skills, mistakes worth documenting."
3. Parse structured output → nudge candidates.
4. Append to nudge_cache.

Cost: 1 free-model call per 5 turns. ~500 input tokens + ~200 output tokens.

### 4.3 Nudge cache

`nudge_cache.py` — per-trace queue:

```python
@dataclass
class Nudge:
    nudge_type: Literal["memory_save", "skill_create", "skill_fix"]
    content: str          # what to save/create/fix
    source: str           # "rule" | "batch"
    confidence: float     # 0..1
    created_at: float

class NudgeCache:
    def push(self, trace_id: str, nudge: Nudge) -> None: ...
    def pop_all(self, trace_id: str) -> list[Nudge]: ...
    def peek(self, trace_id: str) -> list[Nudge]: ...
```

Max 5 nudges per injection (prevent prompt bloat). Oldest nudges expire after 10 minutes.

### 4.4 Nudge injector

`nudge_injector.py` — called before dispatch in `chat_completions`, after wake-up injection:

```
[LEARNING NUDGE]
- 💾 Save decision: "switched to GraphQL for real-time subscriptions"
  → call mempalace_add_drawer(wing="project", room="decisions", content="...")
- 🔧 Skill candidate: "graphql-schema-generation" pattern detected (3x repeated)
  → call delegate-task to create a reusable skill
```

Inserted as a `## Learning Nudges` block in the system message, after the `## Memory Context` block from P1.

Agent autonomy: the agent sees the nudges and decides whether to act. Nudges are suggestions, not commands.

## 5. Insight generator

Fires as an `on_mine_hook` (alongside P2's analyzer_hook).

1. Search mempalace for the last 5 sessions in the current project wing (`conversations` room, sorted by recency).
2. One LLM call: "Analyze these 5 sessions. What patterns do you see? What is the developer doing well? What mistakes are recurring? What workflow improvements would help?"
3. Output: 3-5 bullet insight report.
4. Store in mempalace: `wing="user", room="insights"`.
5. Next session's wake-up automatically includes insights (P1 wake-up reads user wing).

Cost: 1 free-model call per session close. ~2000 input tokens (5 session summaries) + ~300 output.

## 6. Trajectory compressor

Fires as an `on_mine_hook`, after insight_generator.

1. Receive session transcript (from P1 mining).
2. One LLM call with structured output prompt.
3. Output schema:

```json
{
  "session_id": "trace_id_hex",
  "timestamp": "ISO8601",
  "summary": "1-3 sentences",
  "decisions": [{"what": "str", "why": "str", "outcome": "success|failure|pending"}],
  "mistakes": [{"what": "str", "lesson": "str"}],
  "reusable_patterns": [{"pattern": "str", "context": "str"}],
  "model_performance": {"model_id": {"turns": N, "tool_success_rate": 0.0-1.0}}
}
```

4. Store in mempalace: `wing=project_wing, room="trajectories"`, content=JSON string.
5. P4 (HyperAgent) will query this room to learn "which evolution strategies produced which outcomes."

Cost: 1 free-model call per session close. ~1500 input + ~400 output tokens.

## 7. Conversation buffer

The nudge engine needs access to recent turns without re-querying telemetry every time. `nudge_cache.py` also maintains a lightweight per-trace conversation buffer:

```python
class ConversationBuffer:
    def append_user(self, trace_id: str, content: str) -> None: ...
    def append_assistant(self, trace_id: str, content: str) -> None: ...
    def recent(self, trace_id: str, n: int = 5) -> list[dict]: ...
    def turn_count(self, trace_id: str) -> int: ...
```

Fed from `openai_compat.py`: user messages from the request payload, assistant messages from the provider response. Same data that P1's transcript reconstruction uses, but kept in-memory for real-time access.

## 8. Error handling

| Scenario | Handling |
|---|---|
| rule_detector regex error | Log, skip nudge. Rules are simple; unlikely to fail. |
| batch_analyzer LLM fails | Skip this batch. Retry at next 5-turn boundary. |
| batch_analyzer returns unparseable output | Discard, log warning. No nudge from this batch. |
| nudge_cache overflow (>5 per trace) | Drop lowest-confidence nudges. |
| nudge_injector finds empty cache | No injection — passthrough (zero overhead). |
| insight_generator mempalace search returns <2 sessions | Skip insight generation (not enough data). |
| insight_generator LLM fails | Log, skip. Insights are nice-to-have; next session will try again with more data. |
| trajectory_compressor LLM fails | Log. Raw transcript is already in mempalace (P1 convos mining). No data loss. |

## 9. Testing strategy

| Module | Tests | Method |
|---|---|---|
| `rule_detector` | Keyword matching, code-repeat detection, confidence scoring | Unit: fixture responses |
| `batch_analyzer` | LLM prompt construction, output parsing, 5-turn trigger | Unit: mock LLM |
| `nudge_cache` | Push/pop/peek, expiry, max-5 limit, conversation buffer | Unit: in-memory |
| `nudge_injector` | System message prepend, empty cache passthrough | Unit: fixture payloads |
| `insight_generator` | mempalace search mock, LLM prompt, output storage | Unit: mock mempalace + LLM |
| `trajectory_compressor` | Transcript → structured JSON, schema validation | Unit: mock LLM |
| Integration | Full turn cycle: response → rule detect → nudge → inject → verify | FastAPI TestClient |

## 10. Milestones

| # | Deliverable | Exit criterion |
|---|---|---|
| M0 | rule_detector + nudge_cache + nudge_injector wired | "decided to" in response → next turn has `[LEARNING NUDGE]` in system message |
| M1 | batch_analyzer (5-turn) | After 5 turns, batch nudge appears alongside rule nudges |
| M2 | insight_generator | Session close → insights in user wing → next wake-up includes them |
| M3 | trajectory_compressor | Session close → structured JSON in project/trajectories room |

## 11. Decisions log

| # | Decision | Rationale |
|---|---|---|
| D1 | C: nudge + insights + trajectory (full Hermes learning loop) | Maximum learning capability; trajectory data needed for P4 |
| D2 | B+C hybrid nudge: rules (instant) + batch (5-turn LLM) | Rules catch obvious patterns at zero cost; batch catches subtleties |
| D3 | C: trajectory as structured JSON (not DAG, not instruction pairs) | Readable by humans and P4; natural extension of P1 general mining |

---

**End of design.**
