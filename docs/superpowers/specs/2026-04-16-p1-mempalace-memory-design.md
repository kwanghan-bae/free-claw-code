# P1 — Mempalace Ultra-Long-Term Memory (Design)

- **Date:** 2026-04-16
- **Status:** Draft — awaiting user review
- **Owner:** kwanghan-bae
- **Parent program:** free-claw-code self-evolving coding agent (P0 → P1 → P2 → P3 → P4)
- **Depends on:** P0 (free LLM router sidecar, merged `00d8a3d`)
- **Follow-ups this spec enables:** P2 (OpenSpace skill evolution), P3 (Hermes learning loop), P4 (HyperAgent meta-self-modification)

## 1. Context

P0 delivered a Python sidecar (`free-claw-router/`) that intercepts all claw LLM traffic, routes through free providers, tracks telemetry in SQLite, and manages quota. P1 adds ultra-long-term memory so that every session's decisions, problems, and context are preserved across sessions and recoverable on demand.

The memory substrate is [mempalace](https://github.com/milla-jovovich/mempalace) — a ChromaDB-based system with a Palace hierarchy (Wings → Rooms → Closets → Drawers), LongMemEval 96.6% R@5 in raw verbatim mode, 29 MCP tools, fully local and free.

P1 integrates mempalace into the claw + sidecar stack via two paths:
- **Agent path (MCP):** claw's MCP client connects to mempalace's MCP server — the agent can search, add, and browse memories during conversation.
- **Infrastructure path (sidecar):** the sidecar handles wake-up injection, automatic mining on session close, idle-time background mining, and wing management — the agent doesn't need to remember to do these.

## 2. Scope

### In scope (P1)

1. **Wake-up injection** — sidecar prepends project + user memory context to the first request's system message, transparently at HTTP level. Re-injects on idle-recovery.
2. **Automatic session mining** — on session close, sidecar reconstructs the conversation transcript from telemetry and runs mempalace `mine` in dual mode (convos + general).
3. **Idle background mining** — when no request arrives for 30+ minutes, sidecar runs intermediate mining on the transcript-so-far, invalidates wake-up cache.
4. **Palace wing structure** — per-project wing (basename of workspace dir) + global `user` wing. Rooms: `conversations`, `decisions`, `problems`, `milestones`, `preferences`.
5. **Auto-fallback search** — agent's `mempalace_search` defaults to current-project wing; falls back to global search if results are insufficient.
6. **MCP server registration** — mempalace MCP server configured in `.claude.json` for agent-driven search/add.
7. **Workspace header** — claw emits `x-free-claw-workspace` header so sidecar can resolve the current project wing.

### Out of scope (deferred)

- **Hermes memory_manager integration** — P3 scope; P1 provides the storage substrate they'll consume.
- **Skill-memory cross-referencing** — P2 (OpenSpace) will query the `skill_model_affinity` readmodel + mempalace together; P1 just stores.
- **AAAK compression dialect** — mempalace's experimental lossy compression. Raw verbatim mode is the default (96.6% recall). AAAK can be enabled later without architectural change.
- **Knowledge graph wiring** — mempalace has `knowledge_graph.py` and `fact_checker.py` but they're not yet production-ready upstream. Defer to a follow-up.
- **Multi-user memory isolation** — single user (the owner) assumed.

## 3. Architecture

### 3.1 Two-path topology

```
┌──────────────────────────────────────────────────────────┐
│ claw CLI (Rust)                                           │
│                                                           │
│  MCP Client ──stdio──► mempalace MCP Server (29 tools)   │
│  (agent calls mempalace_search, mempalace_add_drawer)    │
│                                                           │
│  ──HTTP──► free-claw-router sidecar                      │
│            OPENAI_BASE_URL=http://127.0.0.1:7801         │
└──────────────────────────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   ┌──────────┐   ┌──────────┐   ┌──────────────┐
   │ wake-up  │   │ auto     │   │ idle         │
   │ injector │   │ mining   │   │ mining       │
   │          │   │ (close)  │   │ (30min+)     │
   └──────────┘   └──────────┘   └──────────────┘
         │               │               │
         ▼               ▼               ▼
   ┌──────────────────────────────────────────┐
   │ mempalace Python API (imported directly) │
   │ - wake_up(wing=project)                  │
   │ - wake_up(wing="user")                   │
   │ - mine(transcript, mode=convos)          │
   │ - mine(transcript, mode=general)         │
   │ - search_memories(query, wing=...)       │
   └──────────────────────────────────────────┘
         │
         ▼
   ┌──────────────────────────┐
   │ ChromaDB (~/.mempalace/) │
   │ Wings: per-project + user│
   │ Rooms: conversations,    │
   │   decisions, problems,   │
   │   milestones, preferences│
   └──────────────────────────┘
```

### 3.2 New sidecar modules

```
free-claw-router/router/memory/
├── __init__.py
├── wing_manager.py       # workspace path → wing name mapping + SQLite persistence
├── wakeup.py             # mempalace wake_up calls + TTL cache (5min)
├── injector.py           # first-request detection + system message prepend
├── transcript.py         # telemetry spans → conversation transcript reconstruction
├── miner.py              # dual-mode mine (convos + general) with wing/room routing
└── idle_detector.py      # APScheduler job: check last-request timestamp, trigger mining
```

### 3.3 Existing sidecar modules touched

| File | Change |
|---|---|
| `router/server/openai_compat.py` | Add 3 lines: `from router.memory.injector import maybe_inject_wakeup` + call in `chat_completions` before dispatch |
| `router/server/lifespan.py` | Initialize `idle_detector` APScheduler job on startup, stop on shutdown |

### 3.4 claw-side changes (minimal)

| File | Change |
|---|---|
| `rust/crates/runtime/src/prompt.rs` | Add `x-free-claw-workspace` header from `session.workspace_root` (~3 lines) |
| `.claude.json` | Add `mcpServers.mempalace` entry |

No other Rust code changes.

## 4. Wing & Room structure

### 4.1 Wing naming

`wing_manager.py` maps workspace root to wing name:

```
/Users/joel/Desktop/git/free-claw-code  →  wing "free-claw-code"
/Users/joel/Desktop/git/korea-inflation-rpg  →  wing "korea-inflation-rpg"
(always)  →  wing "user"
```

Rule: `Path(workspace_root).name`. Stored in `telemetry.db` table `wing_mappings(workspace_path TEXT PRIMARY KEY, wing_name TEXT)`.

### 4.2 Room assignment

| Room | Content | Mining mode | Wing |
|---|---|---|---|
| `conversations` | Verbatim session transcripts | `convos` | per-project |
| `decisions` | Extracted decisions ("we chose X because Y") | `general` | per-project |
| `problems` | Extracted problems ("X failed because Y") | `general` | per-project |
| `milestones` | Extracted milestones ("shipped feature Z") | `general` | per-project |
| `preferences` | Extracted work-style preferences | `general` | `user` wing |

### 4.3 Search fallback chain

1. `mempalace_search(query, wing=current_project)` — project-scoped
2. If < 2 results with distance < 0.7: retry `mempalace_search(query)` — global
3. Results merged, deduplicated, top-N returned

This logic lives in a thin wrapper function in `router/memory/search_fallback.py` (optional — the MCP server's native search already supports wing=None for global). The sidecar exposes this as `GET /memory/search?q=...&wing=...` for programmatic consumers (P2/P3).

## 5. Wake-up injection

### 5.1 Trigger

`injector.py` maintains a `set[str]` of seen `trace_id` values (in-memory). When a request arrives:

- Parse `traceparent` header → extract `trace_id`
- If `trace_id` is new OR last request for this `trace_id` was > 30 minutes ago: inject wake-up
- Otherwise: passthrough

### 5.2 Injection format

```python
MEMORY_BLOCK = """

## Memory Context (auto-injected by mempalace)

### Project: {project_wing}
{project_wakeup_text}

### Your preferences & patterns
{user_wakeup_text}
"""
```

Appended to `messages[0].content` (system role). If no system message exists, one is created.

### 5.3 Wake-up content

`wakeup.py` calls:
- `mempalace.layers.PalaceLayer.wake_up(wing=project_wing)` → ~600-900 tokens of project context
- `mempalace.layers.PalaceLayer.wake_up(wing="user")` → ~200-400 tokens of user preferences

Combined: ~800-1300 tokens per injection. Within free-tier context budgets.

### 5.4 Cache

TTL = 5 minutes. Key = `(project_wing, "user")`. Invalidated by idle_detector after mining completes (so returning user gets fresh context).

## 6. Automatic mining

### 6.1 Session close detection

The sidecar has no explicit "session close" signal. Detection: when a `trace_id` has received no requests for 5 minutes, consider that session closed. Checked by APScheduler every 1 minute.

### 6.2 Transcript reconstruction

`transcript.py` queries `telemetry.db`:

```sql
SELECT e.payload_json
FROM events e
JOIN spans s ON e.span_id = s.span_id
WHERE s.trace_id = ?
ORDER BY e.ts ASC
```

Extracts user messages and assistant responses from the event payloads. Formats as:

```markdown
## Session {trace_id_hex[:8]} — {timestamp}

**User:** {message}

**Assistant:** {response}

---
```

### 6.3 Dual mining

For each closed session:

1. Write transcript to a temp file
2. `mempalace.convo_miner.mine_convos(temp_file, wing=project_wing, room="conversations")`
3. `mempalace.general_extractor.extract(temp_file, wing=project_wing)` → auto-routes to `decisions`, `problems`, `milestones` rooms
4. Filter `preferences` category from general extraction → `mempalace.add_drawer(wing="user", room="preferences", content=...)`
5. Delete temp file
6. Record mining event in telemetry

### 6.4 Delta mining

If idle mining already processed T=0 to T=30m, session close mining only processes T=30m to T=end. `miner.py` tracks `last_mined_event_ts` per `trace_id` in `telemetry.db`:

```sql
CREATE TABLE IF NOT EXISTS mining_state(
  trace_id BLOB PRIMARY KEY,
  last_mined_event_ts INTEGER NOT NULL,
  last_mined_at INTEGER NOT NULL
);
```

### 6.5 Idle mining

`idle_detector.py` — APScheduler job running every 60 seconds:

1. Query `last_request_ts` per active `trace_id` from in-memory tracker
2. If `now - last_request_ts > 1800` (30 min) AND `trace_id` not yet idle-mined:
   - Run mining pipeline on transcript-so-far (delta from `last_mined_event_ts`)
   - Invalidate wake-up cache
   - Mark `trace_id` as idle-mined (prevent re-mining same idle window)

## 7. Error handling

| Scenario | Handling | Rationale |
|---|---|---|
| Wake-up fails (ChromaDB error) | Skip injection, log warning, proceed with empty memory | Memory is enhancement, not critical path |
| Mining fails (transcript parse error) | Log error, retain `mining_state` at last good position, retry next cycle | Transcript data persists in telemetry DB |
| mempalace MCP process dies | claw's MCP lifecycle handles reconnect | Agent search unavailable; infra path (sidecar) unaffected |
| Idle mining + user returns simultaneously | Mining runs to completion (async), request processed immediately | Mining reads telemetry (immutable), writes ChromaDB (append-only) — no conflict |
| Duplicate mining attempt | `mempalace.palace.file_already_mined` + content hash dedup | Built-in mempalace safety |
| Wing doesn't exist yet | `mempalace.add_drawer` auto-creates wing + room on first write | Native mempalace behavior |
| `x-free-claw-workspace` header missing | Fallback to `"default"` wing name | Graceful degradation |
| ChromaDB corrupted | mempalace `repair` CLI command exists; sidecar logs error and disables memory features until repaired | Don't crash the routing layer for memory issues |

## 8. Testing strategy

| Layer | Tests | Method |
|---|---|---|
| `wing_manager` | workspace→wing mapping, persistence, duplicates | Unit: SQLite tmp_path |
| `wakeup` | project+user merge, TTL cache hit/miss/invalidate | Unit: mock mempalace PalaceLayer |
| `injector` | first-request inject, passthrough on repeat, idle-recovery re-inject | Unit: mock trace_id set + request fixtures |
| `transcript` | spans→markdown reconstruction, delta calculation | Unit: fixture spans in tmp SQLite |
| `miner` | convos+general dual call, wing/room routing, preference→user wing | Unit: mock mempalace mine/extract |
| `idle_detector` | 30min threshold, re-entry prevention, cache invalidation | Unit: manipulated timestamps |
| Integration | end-to-end: request→inject→idle→mine→re-inject | FastAPI TestClient + tmp mempalace palace |
| MCP | `.claude.json` registration + `mempalace_search` smoke | Manual: start claw, verify tool listing |

## 9. Milestones

| # | Deliverable | Exit criterion |
|---|---|---|
| M0 | `wing_manager` + `wakeup` + `injector` | First request to sidecar contains wake-up context in system message |
| M1 | `transcript` + `miner` + session-close mining | After session ends, `mempalace search` returns content from that session |
| M2 | `idle_detector` + idle mining + cache invalidation | 30min idle → return → wake-up reflects just-mined content |
| M3 | MCP registration + `x-free-claw-workspace` header + integration smoke | claw agent calls `mempalace_search` via MCP and gets results |

## 10. Risks & mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| mempalace upstream breaking changes | Medium | Pin version in `pyproject.toml`; import via `try/except` with version check |
| ChromaDB embedding model mismatch after upgrade | Medium | mempalace uses its own embedding config; lock `chromadb` version range |
| Wake-up token budget exceeds free model context | Low | wake_up output is ~800-1300 tokens; smallest free model (Groq llama 32K) has ample room. Add a hard truncation at 2000 tokens as safety. |
| Idle mining fires during active debugging (user stepped away briefly) | Low | 30 minutes is conservative; worst case is mining an incomplete session, which is append-safe |
| General extractor quality on free models | Medium | mempalace's general extractor is designed for Claude/GPT but works on any LLM. Test with Groq llama-3.3-70b; if quality is poor, fall back to convos-only mining |
| Telemetry DB doesn't capture full assistant responses | Medium | Verify P0's span/event recording includes response content; if not, add an event for `assistant_response` in `openai_compat.py` |

## 11. Decisions log

| # | Decision | Rationale |
|---|---|---|
| D1 | B+idle: wake-up on start, auto mining on close, idle mining at 30min | Balances recall freshness with token/complexity cost |
| D2 | C: per-project wing + user wing | Project isolation with cross-project knowledge via user wing and tunnel feature |
| D3 | C: convos + general dual mining | Verbatim for recall guarantee, general for efficient wake-up |
| D4 | C: MCP for agent search, sidecar for infra (wake-up/mining/idle) | Each path does what it's best at; no redundant reimplementation |
| D5 | B: system message prepend at HTTP level | Zero claw Rust code change; sidecar transparently injects |

---

**End of design.**
