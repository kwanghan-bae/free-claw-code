# P2 — OpenSpace Skill Self-Evolution (Design)

- **Date:** 2026-04-16
- **Status:** Draft — awaiting user review
- **Owner:** kwanghan-bae
- **Parent program:** free-claw-code self-evolving coding agent (P0 → P1 → P2 → P3 → P4)
- **Depends on:** P0 (telemetry spans/evaluations), P1 (session mining pipeline)
- **Follow-ups this spec enables:** P3 (Hermes learning loop), P4 (HyperAgent meta-self-modification of the evolver)

## 1. Context

P0 delivered telemetry (traces/spans/events/evaluations in SQLite) and a `skill_model_affinity` readmodel. P1 added session transcript mining with mempalace. P2 adds the skill self-evolution layer so that the agent's capabilities improve autonomously after every session.

The evolution engine is [OpenSpace](https://github.com/HKUDS/OpenSpace) (HKUDS) — a proven skill self-evolution system with FIX/DERIVED/CAPTURED 3-mode evolution, BM25+embedding skill ranking, version DAG tracking, and quality monitoring. OpenSpace demonstrated 4.2x income improvement on GDPVal economic benchmarks.

P2 integrates OpenSpace via two paths (matching the P0/P1 pattern):
- **Agent path (MCP):** OpenSpace MCP server registered in claw for agent-driven `delegate-task` and `skill-discovery`.
- **Infrastructure path (sidecar):** Three evolution triggers run automatically — post-session analysis (wired into P1 mining), tool degradation monitor, and metric monitor.

## 2. Scope

### In scope

1. **Vendor OpenSpace `skill_engine/`** — copy ~10 files from `OpenSpace/openspace/skill_engine/` into `free-claw-router/router/vendor/openspace_engine/`. Strip external deps (litellm, grounding, cloud) — only the skill lifecycle core.
2. **Sidecar bridge module** — initialize OpenSpace store at `~/.free-claw-router/openspace.db`, manage skill CRUD through vendored `store.py`.
3. **Post-session analyzer hook** — wired into P1's session-close mining pipeline. When transcript mining runs, simultaneously feed the transcript to OpenSpace `analyzer.py` for skill involvement analysis and evolution suggestions.
4. **Three evolution triggers** via APScheduler:
   - Post-session: fires with P1 mining, feeds analyzer output to evolver.
   - Tool degradation: reads P0 `evaluations` table, detects tool success rate drops, batch-evolves dependent skills.
   - Metric monitor: periodic scan of skill health (applied rate, completion rate, fallback rate) from `openspace.db`.
5. **MCP registration** — OpenSpace MCP server in `.claude.json` + `delegate-task` / `skill-discovery` host skills copied to claw's skills directory.
6. **Hybrid skill_id resolution** — delegate-task provides exact skill_id (path A); sidecar post-session analyzer infers skill involvement from transcript (path C fallback).

### Out of scope

- **OpenSpace cloud community** — no `OPENSPACE_API_KEY` integration. Local-only evolution.
- **Skill-model affinity feedback into router** — P0's `skill_model_affinity` readmodel exists but connecting it to `routing/score.py` is deferred to P4 (HyperAgent edits the scoring function).
- **OpenSpace grounding/agents/communication modules** — not vendored, not used. We use only `skill_engine/`.
- **OpenSpace frontend dashboard** — not integrated. Skill inspection is via CLI or DB queries.

## 3. Architecture

### 3.1 Two-path topology

```
┌──────────────────────────────────────────────────────────┐
│ claw CLI (Rust)                                           │
│                                                           │
│  MCP Client ──stdio──► OpenSpace MCP Server (4 tools)    │
│  (delegate-task, skill-discovery, search, execute)       │
│                                                           │
│  ──HTTP──► free-claw-router sidecar                      │
└──────────────────────────────────────────────────────────┘
                         │
         ┌───────────────┼─────────────────┐
         ▼               ▼                 ▼
   ┌──────────┐   ┌─────────────┐   ┌──────────────┐
   │ post-    │   │ tool        │   │ metric       │
   │ session  │   │ degradation │   │ monitor      │
   │ analyzer │   │ monitor     │   │              │
   └──────────┘   └─────────────┘   └──────────────┘
         │               │                 │
         ▼               ▼                 ▼
   ┌──────────────────────────────────────────────┐
   │ vendor/openspace_engine/                      │
   │ registry → analyzer → evolver → store         │
   └──────────────────────────────────────────────┘
         │                                    │
         ▼                                    ▼
   telemetry.db (read)              openspace.db (read/write)
```

### 3.2 New sidecar modules

```
free-claw-router/router/skills/
├── __init__.py
├── bridge.py             # OpenSpace store init, path config, skill CRUD wrapper
├── analyzer_hook.py      # P1 mining callback → OpenSpace analyzer
├── triggers.py           # 3 APScheduler jobs
└── adapter.py            # telemetry readmodels → analyzer input format

free-claw-router/router/vendor/openspace_engine/
├── __init__.py
├── registry.py           # BM25+embedding skill discovery
├── analyzer.py           # post-execution analysis
├── evolver.py            # FIX/DERIVED/CAPTURED evolution
├── store.py              # SQLite skill DAG + quality metrics
├── patch.py              # multi-file FULL/DIFF/PATCH application
├── types.py              # SkillRecord, SkillLineage, EvolutionSuggestion
├── skill_ranker.py       # hybrid ranking
├── fuzzy_match.py        # skill name fuzzy matching
├── conversation_formatter.py  # format execution history for analyzer
└── skill_utils.py        # shared utilities
```

### 3.3 Existing modules touched

| File | Change |
|---|---|
| `router/server/lifespan.py` | Initialize skills bridge + register 3 trigger jobs |
| `router/memory/idle_detector.py` | Add `on_session_close` callback list so analyzer_hook can register |
| `.claude.json` | Add `openspace` MCP server entry |

### 3.4 claw-side changes — none

No Rust code changes. MCP registration and host skills are config/file additions only.

## 4. Vendor strategy

### 4.1 What to copy

From `OpenSpace/openspace/skill_engine/` — all `.py` files (~10 files, ~3000 LOC total).

### 4.2 What to strip

Any import of `openspace.llm`, `openspace.grounding`, `openspace.cloud`, `openspace.agents`, `litellm` must be replaced with a thin adapter that routes LLM calls through our sidecar's existing `DispatchClient`. This adapter lives in `router/skills/adapter.py`.

### 4.3 Upstream sync

Monthly manual diff against upstream `OpenSpace/openspace/skill_engine/`. Same pattern as the P0 catalog refresh PR loop — a claw CronCreate job can automate the diff generation + PR.

## 5. Evolution triggers

### 5.1 Post-session analyzer

Fires when P1's `SessionCloseDetector` triggers mining. Added as a callback:

```python
# In idle_detector.py's _do_mine, after mempalace mining:
for hook in self._on_mine_hooks:
    hook(trace_id, transcript, wing)
```

`analyzer_hook.py` registers itself as a mine hook:

1. Receives `(trace_id, transcript, wing)`
2. Calls vendored `analyzer.analyze(transcript, skill_db)` → list of `EvolutionSuggestion`
3. For each suggestion, calls vendored `evolver.evolve(suggestion, skill_db)` → new skill version
4. Logs evolution event to telemetry

### 5.2 Tool degradation monitor

APScheduler job, runs every 15 minutes:

1. Query P0 `evaluations` table: per-tool `score_value` rolling 1-hour average
2. Compare against 24-hour baseline
3. If any tool's success rate dropped >20%: find skills that reference that tool (via `openspace.db` skill content search)
4. Trigger batch evolution for those skills

### 5.3 Metric monitor

APScheduler job, runs every 30 minutes:

1. Query `openspace.db` skill metrics: applied_count, success_count, error_count per skill
2. Flag skills where `error_count / (applied_count + 1) > 0.3` (30% error rate)
3. Trigger FIX evolution for flagged skills

## 6. Adapter — LLM calls from OpenSpace through our router

OpenSpace's `evolver.py` and `analyzer.py` make LLM calls (to generate diffs, analyze transcripts). Originally they use `litellm`. We replace with:

```python
# router/skills/adapter.py
async def call_llm(prompt: str, system: str = "", model: str = None) -> str:
    """Route OpenSpace LLM calls through our sidecar's own dispatch."""
    from router.dispatch.client import DispatchClient
    client = DispatchClient()
    # Use internal loopback — sidecar calls itself
    result = await client.call(
        provider=_get_default_provider(),
        model=_get_default_model(),
        payload={"messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]},
        upstream_headers={"x-free-claw-hints": "coding"},
    )
    return result.body.get("choices", [{}])[0].get("message", {}).get("content", "")
```

This means OpenSpace evolution uses the same free-model routing + quota management as the agent. No separate LLM configuration needed.

## 7. Skill storage

Two separate SQLite databases:

| Database | Owner | Content |
|---|---|---|
| `~/.free-claw-router/telemetry.db` | P0 sidecar | traces, spans, events, evaluations, wing_mappings, mining_state |
| `~/.free-claw-router/openspace.db` | vendored store.py | skills, skill_versions, skill_metrics, evolution_log |

Cross-query happens in Python (`adapter.py` reads telemetry, writes evolution results to both DBs as appropriate).

## 8. Error handling

| Scenario | Handling |
|---|---|
| Analyzer fails | Log warning, skip evolution suggestions for this session. Transcript remains in mempalace for future analysis. |
| Evolver produces invalid patch | Vendored `evolver.py` validates before replacing. Failed evolution logged in `openspace.db` evolution_log. Old skill version retained. |
| Anti-loop guard | OpenSpace has built-in: max 3 evolution attempts per skill per 24h. |
| LLM adapter fails (all free models exhausted) | Evolution deferred to next trigger cycle. No data loss. |
| `openspace.db` corrupted | Sidecar logs error, disables skill evolution features. MCP path unaffected (OpenSpace MCP has its own DB instance). |
| Vendored code has upstream bug | We own the vendor copy — fix directly + upstream PR. |

## 9. Testing strategy

| Layer | Tests | Method |
|---|---|---|
| `bridge` | Store init, skill CRUD, path resolution | Unit: tmp_path SQLite |
| `adapter` | telemetry readmodels → analyzer input format | Unit: fixture data |
| `analyzer_hook` | Callback registration, transcript→suggestions | Unit: mock analyzer |
| `triggers` | Degradation detection threshold, metric flagging | Unit: fixture evaluations |
| `vendor/openspace_engine` | Ensure vendored code imports cleanly without litellm | Import smoke test |
| Integration | Session → mining → analysis → evolution → new version in DB | End-to-end with mock LLM |

## 10. Milestones

| # | Deliverable | Exit criterion |
|---|---|---|
| M0 | Vendor copy + bridge + store init | `openspace.db` created, skill CRUD works via bridge |
| M1 | MCP registration + host skills | claw `delegate-task` / `skill-discovery` MCP calls succeed |
| M2 | analyzer_hook + 3 triggers wired | Session close → skill analysis runs → evolution suggestion in DB |
| M3 | Integration smoke | Intentional skill failure → auto FIX → next run uses fixed version |

## 11. Decisions log

| # | Decision | Rationale |
|---|---|---|
| D1 | B: MCP + sidecar evolution triggers | Infrastructure-driven evolution; don't rely on free-model agent autonomy |
| D2 | C: Copy skill_engine/ only, strip heavy deps | Avoid litellm/chromadb conflicts; own only what we use; P4-editable |
| D3 | C: Hybrid skill_id — delegate-task exact + sidecar post-session inference | Best accuracy with full coverage |
| D4 | A: Separate openspace.db, cross-query in Python | Avoid upstream schema migration burden; store.py manages its own schema |

---

**End of design.**
