# P4 — HyperAgent Meta-Self-Modification (Design)

- **Date:** 2026-04-17
- **Status:** Draft — awaiting user review
- **Owner:** kwanghan-bae
- **Parent program:** free-claw-code self-evolving coding agent (P0 → P1 → P2 → P3 → P4)
- **Depends on:** P0 (routing policy, telemetry, PR loop), P1 (mempalace), P2 (OpenSpace evolver/analyzer prompts), P3 (trajectory data, learning prompts, rule patterns)
- **Paper reference:** [HyperAgents (Meta, arXiv 2603.19461)](https://arxiv.org/abs/2603.19461) — metacognitive self-modification where the meta-level procedure itself is editable.

## 1. Context

P0–P3 delivered a self-evolving coding agent with free-only LLM routing (P0), ultra-long-term memory (P1), skill self-evolution (P2), and an active learning loop (P3). However, the *policies* governing these systems — routing priorities, evolution prompts, nudge patterns, trigger thresholds — are static. A human must manually tune them.

P4 closes the final loop: the agent's evolution mechanisms evolve themselves. Inspired by Meta's HyperAgent paper, where task agent + meta agent merge into a single editable program, P4 adds a meta-layer that:
1. Analyzes trajectory data to propose edits to policies and prompts
2. Builds consensus across multiple sessions before applying
3. Executes edits through the existing PR review loop (safety)
4. Automatically rolls back edits that degrade performance

## 2. Scope

### In scope

1. **Meta analyzer** — on session close (via on_mine_hook), reads P3 trajectory data, compares against current config/prompts, generates `MetaSuggestion` edit candidates.
2. **Suggestion accumulator** — appends suggestions to `~/.free-claw-router/meta_suggestions.json` with timestamps and trace_ids.
3. **Consensus engine** — daily cron job. Groups suggestions by target file + edit direction. Requires 3+ sessions pointing the same way before confirming an `EditPlan`.
4. **Meta editor** — executes confirmed EditPlans. Type-aware: YAML edits via pyyaml, prompt_only edits via string constant replacement, config_only via number/pattern replacement. Constrained to registered targets only.
5. **PR integration** — every edit goes through P0's worktree → gh pr → Claude review → human approval pipeline.
6. **Evaluator + auto-rollback** — after 5 sessions post-edit, compares telemetry metrics (success_rate, skill_model_affinity, nudge acceptance) against pre-edit baseline. Degradation → automatic revert PR.
7. **Edit target registry** — `meta_targets.yaml` declares exactly which files and which edit types are allowed.

### Edit targets (day-1)

| File | Edit type | What can change |
|---|---|---|
| `router/routing/policy.yaml` | yaml | Priority order, fallback_any flags |
| `router/vendor/openspace_engine/shims/prompts.py` | prompt_only | Evolver/analyzer system prompt strings |
| `router/learning/rule_detector.py` | config_only | Regex pattern constants |
| `router/learning/batch_analyzer.py` | prompt_only | SYSTEM_PROMPT constant |
| `router/learning/insight_generator.py` | prompt_only | INSIGHT_PROMPT constant |
| `router/learning/trajectory_compressor.py` | prompt_only | COMPRESS_PROMPT constant |
| `router/skills/triggers.py` | config_only | Threshold numbers (0.7, 0.3) |

### Out of scope

- **Python code logic editing** — only string/number constants. Full code editing deferred until free-model code generation quality improves. Extension path: add `type: python` to `meta_targets.yaml`.
- **Routing score.py learned weights** — P0's `score.py` has a `static_score` stub. P4 edits the prompt/config layer, not the scoring function body. Online learning (Thompson sampling) is a separate future feature.
- **Self-modifying the meta-layer itself** — the paper's deepest recursion ("improving how you improve how you improve"). Deferred. P4 edits P0–P3 policies; P4's own prompts/logic are not in `meta_targets.yaml`. Can be added later by registering `router/meta/meta_analyzer.py` as a target.

### Safety guarantees

1. **Edit scope**: only files in `meta_targets.yaml`, only declared edit types
2. **Consensus**: minimum 3 sessions agreeing on same direction
3. **PR review**: Claude review + human approval (P0 pipeline)
4. **Auto-rollback**: 5-session evaluation window; revert on degradation
5. **Daily cap**: maximum 2 edits per day

## 3. Architecture

```
per session close (on_mine_hook):
  P3 trajectory
    → meta_analyzer: compare trajectory outcomes vs current config
    → MetaSuggestion → meta_suggestions.json

daily cron (03:00):
  meta_suggestions.json
    → meta_consensus: group by (target, direction), filter ≥3 votes
    → EditPlan[]
    → meta_editor: apply edits (type-aware)
    → meta_pr: worktree → gh pr create → Claude review
    → human approves → merge → sidecar hot-reload

5 sessions after edit merge:
  meta_evaluator:
    compare telemetry pre-edit vs post-edit
    → improved: keep
    → degraded: auto-revert PR
    → inconclusive: observe 5 more sessions (max 15)
```

### 3.1 New sidecar modules

```
free-claw-router/router/meta/
├── __init__.py
├── meta_targets.yaml        # edit target registry
├── meta_analyzer.py         # trajectory → edit suggestions
├── meta_suggestions.py      # JSON accumulator (read/write/prune)
├── meta_consensus.py        # majority vote → EditPlan
├── meta_editor.py           # type-aware file editing
├── meta_evaluator.py        # pre/post comparison → keep/revert
└── meta_pr.py               # reuse P0 PR loop (worktree + gh)
```

### 3.2 Existing modules touched

| File | Change |
|---|---|
| `router/server/lifespan.py` | Init meta modules, register meta_analyzer as on_mine_hook, register daily cron |
| `router/memory/idle_detector.py` | meta_analyzer registered alongside P2/P3 hooks |

## 4. MetaSuggestion schema

```json
{
  "id": "uuid",
  "trace_id": "session trace hex",
  "timestamp": "ISO8601",
  "target_file": "router/routing/policy.yaml",
  "edit_type": "yaml",
  "direction": "promote groq/llama-3.3-70b for coding",
  "rationale": "Last 3 sessions: Groq had 95% tool success vs OpenRouter 78%",
  "confidence": 0.82,
  "proposed_diff": "coding.priority[0] = [groq, llama-3.3-70b-versatile]"
}
```

## 5. EditPlan schema

```json
{
  "id": "uuid",
  "target_file": "router/routing/policy.yaml",
  "edit_type": "yaml",
  "description": "Promote Groq for coding tasks",
  "supporting_suggestions": ["suggestion_id_1", "suggestion_id_2", "suggestion_id_3"],
  "sessions_observed": 5,
  "pre_edit_snapshot": "git SHA of current file",
  "proposed_change": { "path": "task_types.coding.priority.0", "value": ["groq", "llama-3.3-70b-versatile"] }
}
```

## 6. Meta editor — type-aware editing

### yaml type
Load with pyyaml, navigate to the specified path, update value, dump back. Validate schema after edit (reuse P0 catalog schema pattern).

### prompt_only type
Parse the target Python file as text. Find the constant (e.g., `SYSTEM_PROMPT = """..."""`). Replace the string content between triple-quotes. Do NOT modify any other code. Validate: re-import the module after edit to confirm no SyntaxError.

### config_only type
Find the constant assignment (e.g., `_DECISION_RE = re.compile(r"...")`). Replace the pattern string or numeric value. Validate: re-import the module.

## 7. Evaluation metrics

`meta_evaluator` compares these across pre-edit and post-edit windows:

| Metric | Source | Better = |
|---|---|---|
| `overall_success_rate` | telemetry spans `status='ok' / total` | higher |
| `tool_success_rate` | telemetry spans where `op_name='tool_call'` | higher |
| `skill_evolution_success` | openspace.db evolution_log `status='applied'` | higher |
| `nudge_acceptance_rate` | count of MCP calls following nudges / total nudges | higher |
| `avg_session_duration` | telemetry traces duration | stable or lower (faster = better) |
| `trajectory_mistake_count` | P3 trajectory `mistakes[]` length | lower |

Degradation threshold: any metric drops >15% AND no metric improves >15% → revert. If mixed (some up, some down) → inconclusive, observe more.

## 8. Error handling

| Scenario | Handling |
|---|---|
| meta_analyzer fails | Log, skip suggestion. Next session retries. |
| suggestions.json corrupt | Backup + recreate empty. Lost suggestions ≈ delay, not data loss. |
| Consensus never reached (<3 sessions agree) | No edit. Suggestions expire after 7 days. |
| meta_editor parse/edit error | Skip edit, log. PR not created. |
| meta_editor produces invalid file (import fails) | Reject edit immediately, log. |
| PR review rejects edit | Log rejection reason. Suggestion direction marked "rejected" — same direction won't be proposed for 7 days. |
| Evaluator metrics unavailable (too few sessions) | Extend observation window. Max 15 sessions then auto-keep (insufficient data = no revert). |
| Revert PR fails | Alert in telemetry. Manual intervention needed. |
| Daily cap hit | Remaining edits queued for tomorrow. |

## 9. Testing strategy

| Module | Tests | Method |
|---|---|---|
| `meta_analyzer` | Trajectory → suggestion generation | Unit: fixture trajectories |
| `meta_suggestions` | JSON CRUD, expiry, dedup | Unit: tmp_path file |
| `meta_consensus` | Grouping, vote threshold, direction matching | Unit: fixture suggestions |
| `meta_editor` | YAML edit, prompt_only edit, config_only edit, validation | Unit: tmp files + re-import |
| `meta_evaluator` | Metric comparison, keep/revert/inconclusive decisions | Unit: fixture metrics |
| `meta_pr` | PR creation (mock gh) | Unit: mock subprocess |
| Integration | End-to-end: trajectory → suggestion → consensus → edit → validate | tmp workspace |

## 10. Milestones

| # | Deliverable | Exit criterion |
|---|---|---|
| M0 | meta_targets.yaml + meta_analyzer + meta_suggestions | Session close → suggestion in JSON file |
| M1 | meta_consensus + meta_editor (dry-run) | 3+ matching suggestions → edit preview printed (not applied) |
| M2 | meta_pr + daily cron wiring | Edit → worktree → gh pr → Claude review comment |
| M3 | meta_evaluator + auto-rollback | 5 sessions post-edit → metrics compared → revert PR on degradation |

## 11. Decisions log

| # | Decision | Rationale |
|---|---|---|
| D1 | B: settings + prompts only (no Python code logic) | Free models unreliable for code editing; prompts give 70% of HyperAgent value |
| D2 | C: hybrid — instant suggestions + daily consensus + PR | Balances responsiveness with stability; prevents single-session noise |
| D3 | 5-safety stack: scope limit + 3-vote consensus + PR review + auto-rollback + daily cap | Defense-in-depth against self-modification runaway |

---

**End of design.**
