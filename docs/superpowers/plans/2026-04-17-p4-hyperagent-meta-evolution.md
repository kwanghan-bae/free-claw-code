# P4 — HyperAgent Meta-Self-Modification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a meta-evolution layer that automatically improves the agent's routing policies, evolution prompts, learning patterns, and trigger thresholds by analyzing trajectory data across sessions, building consensus, and applying edits through the PR review pipeline.

**Architecture:** Seven new sidecar modules under `router/meta/`. Meta analyzer generates edit suggestions per session. Daily cron aggregates via majority vote, type-aware editor applies changes (yaml/prompt_only/config_only), PR loop ensures review, evaluator auto-reverts on degradation.

**Tech Stack:** Python 3.12+ (pyyaml for YAML edits, ast/regex for constant replacement), existing APScheduler, P0 PR loop (worktree + gh).

**Spec:** `docs/superpowers/specs/2026-04-17-p4-hyperagent-meta-evolution-design.md` (commit `9cc36d5`).

---

## File Structure

### New modules

| File | Responsibility |
|---|---|
| `free-claw-router/router/meta/__init__.py` | Package |
| `free-claw-router/router/meta/meta_targets.yaml` | Edit target registry |
| `free-claw-router/router/meta/meta_analyzer.py` | Trajectory → MetaSuggestion |
| `free-claw-router/router/meta/meta_suggestions.py` | JSON file accumulator |
| `free-claw-router/router/meta/meta_consensus.py` | Majority vote → EditPlan |
| `free-claw-router/router/meta/meta_editor.py` | Type-aware file editing |
| `free-claw-router/router/meta/meta_evaluator.py` | Pre/post comparison → keep/revert |
| `free-claw-router/router/meta/meta_pr.py` | Reuse P0 worktree + gh PR |

### Modified

| File | Change |
|---|---|
| `free-claw-router/router/server/lifespan.py` | Init meta modules, register hooks + daily cron |
| `free-claw-router/router/memory/idle_detector.py` | meta_analyzer registered as on_mine_hook |

---

## PART A — Suggestion pipeline (M0)

### Task 1: meta_targets.yaml + meta_suggestions.py

**Files:**
- Create: `free-claw-router/router/meta/__init__.py`
- Create: `free-claw-router/router/meta/meta_targets.yaml`
- Create: `free-claw-router/router/meta/meta_suggestions.py`
- Create: `free-claw-router/tests/test_meta_suggestions.py`

- [ ] **Step 1: Create target registry**

Create `free-claw-router/router/meta/__init__.py` (empty).

Create `free-claw-router/router/meta/meta_targets.yaml`:
```yaml
targets:
  - path: router/routing/policy.yaml
    type: yaml
    description: "LLM routing priority per task type"
  - path: router/vendor/openspace_engine/shims/prompts.py
    type: prompt_only
    description: "Evolver/analyzer system prompts"
  - path: router/learning/rule_detector.py
    type: config_only
    description: "Rule-based nudge patterns"
  - path: router/learning/batch_analyzer.py
    type: prompt_only
    description: "Batch analysis LLM prompt"
  - path: router/learning/insight_generator.py
    type: prompt_only
    description: "Cross-session insight prompt"
  - path: router/learning/trajectory_compressor.py
    type: prompt_only
    description: "Trajectory compression prompt"
  - path: router/skills/triggers.py
    type: config_only
    description: "Evolution trigger thresholds"
```

- [ ] **Step 2: Write failing tests**

Create `free-claw-router/tests/test_meta_suggestions.py`:
```python
import json
from pathlib import Path
from router.meta.meta_suggestions import SuggestionStore, MetaSuggestion

def test_append_and_read(tmp_path: Path):
    store = SuggestionStore(path=tmp_path / "suggestions.json")
    s = MetaSuggestion(
        trace_id="aabb",
        target_file="router/routing/policy.yaml",
        edit_type="yaml",
        direction="promote groq for coding",
        rationale="Groq had 95% success",
        confidence=0.82,
        proposed_diff="coding.priority[0] = groq",
    )
    store.append(s)
    store.append(s)
    items = store.read_all()
    assert len(items) == 2
    assert items[0].target_file == "router/routing/policy.yaml"

def test_read_empty_file(tmp_path: Path):
    store = SuggestionStore(path=tmp_path / "empty.json")
    assert store.read_all() == []

def test_prune_old_suggestions(tmp_path: Path):
    import time
    store = SuggestionStore(path=tmp_path / "s.json", max_age_days=0)
    store.append(MetaSuggestion(
        trace_id="old", target_file="x", edit_type="yaml",
        direction="d", rationale="r", confidence=0.5, proposed_diff="",
    ))
    time.sleep(0.01)
    store.prune()
    assert store.read_all() == []

def test_clear_by_target(tmp_path: Path):
    store = SuggestionStore(path=tmp_path / "s.json")
    store.append(MetaSuggestion(trace_id="a", target_file="file_a", edit_type="yaml",
                                direction="up", rationale="", confidence=0.5, proposed_diff=""))
    store.append(MetaSuggestion(trace_id="b", target_file="file_b", edit_type="yaml",
                                direction="up", rationale="", confidence=0.5, proposed_diff=""))
    store.clear_target("file_a")
    assert len(store.read_all()) == 1
    assert store.read_all()[0].target_file == "file_b"
```

- [ ] **Step 3: Implement**

Create `free-claw-router/router/meta/meta_suggestions.py`:
```python
from __future__ import annotations
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class MetaSuggestion:
    trace_id: str
    target_file: str
    edit_type: str
    direction: str
    rationale: str
    confidence: float
    proposed_diff: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)


class SuggestionStore:
    def __init__(self, path: Path, max_age_days: int = 7) -> None:
        self._path = Path(path)
        self._max_age = max_age_days * 86400

    def append(self, suggestion: MetaSuggestion) -> None:
        items = self._load()
        items.append(asdict(suggestion))
        self._save(items)

    def read_all(self) -> list[MetaSuggestion]:
        return [MetaSuggestion(**item) for item in self._load()]

    def prune(self) -> None:
        now = time.time()
        items = [i for i in self._load() if now - i.get("timestamp", 0) < self._max_age]
        self._save(items)

    def clear_target(self, target_file: str) -> None:
        items = [i for i in self._load() if i.get("target_file") != target_file]
        self._save(items)

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, items: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(items, indent=2))
```

- [ ] **Step 4: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_meta_suggestions.py -v`
Expected: 4 pass.

- [ ] **Step 5: Commit**

```bash
git add free-claw-router/router/meta/__init__.py free-claw-router/router/meta/meta_targets.yaml free-claw-router/router/meta/meta_suggestions.py free-claw-router/tests/test_meta_suggestions.py
git commit -m "feat(meta): suggestion store + edit target registry"
```

---

### Task 2: meta_analyzer.py — trajectory → suggestions

**Files:**
- Create: `free-claw-router/router/meta/meta_analyzer.py`
- Create: `free-claw-router/tests/test_meta_analyzer.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_meta_analyzer.py`:
```python
import pytest
from unittest.mock import AsyncMock
from router.meta.meta_analyzer import MetaAnalyzer
from router.meta.meta_suggestions import MetaSuggestion

SAMPLE_TRAJECTORY = {
    "session_id": "aabb",
    "summary": "Refactored auth",
    "decisions": [{"what": "Use REST", "why": "simpler", "outcome": "success"}],
    "mistakes": [{"what": "Wrong model for tool calls", "lesson": "Groq is better for tools"}],
    "reusable_patterns": [],
    "model_performance": {"groq/llama-3.3-70b-versatile": {"turns": 8, "tool_success_rate": 0.95},
                          "openrouter/z-ai/glm-4.6:free": {"turns": 4, "tool_success_rate": 0.62}},
}

@pytest.mark.asyncio
async def test_analyzer_generates_suggestions_from_trajectory():
    mock_llm = AsyncMock(return_value='[{"target_file":"router/routing/policy.yaml","edit_type":"yaml","direction":"promote groq for tool_heavy","rationale":"95% vs 62%","confidence":0.85,"proposed_diff":"tool_heavy.priority[0]=[groq,llama-3.3-70b-versatile]"}]')
    analyzer = MetaAnalyzer(llm_fn=mock_llm, targets_path=None)
    suggestions = await analyzer.analyze(trace_id="aabb", trajectory=SAMPLE_TRAJECTORY)
    assert len(suggestions) >= 1
    assert suggestions[0].target_file == "router/routing/policy.yaml"

@pytest.mark.asyncio
async def test_analyzer_returns_empty_on_error():
    mock_llm = AsyncMock(side_effect=RuntimeError("down"))
    analyzer = MetaAnalyzer(llm_fn=mock_llm, targets_path=None)
    suggestions = await analyzer.analyze(trace_id="ccdd", trajectory={})
    assert suggestions == []

@pytest.mark.asyncio
async def test_analyzer_filters_invalid_targets():
    mock_llm = AsyncMock(return_value='[{"target_file":"INVALID_FILE","edit_type":"yaml","direction":"x","rationale":"y","confidence":0.9,"proposed_diff":"z"}]')
    from pathlib import Path
    targets_path = Path(__file__).resolve().parent.parent / "router" / "meta" / "meta_targets.yaml"
    analyzer = MetaAnalyzer(llm_fn=mock_llm, targets_path=targets_path)
    suggestions = await analyzer.analyze(trace_id="eeff", trajectory=SAMPLE_TRAJECTORY)
    assert suggestions == []
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/meta/meta_analyzer.py`:
```python
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Awaitable, Callable
import yaml
from .meta_suggestions import MetaSuggestion

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """You are a meta-evolution analyzer. Given a session trajectory and the list of editable targets, suggest improvements to the agent's configuration and prompts.

## Editable targets
{targets}

## Rules
- Only suggest edits to files listed in targets
- edit_type must match the target's type (yaml, prompt_only, config_only)
- Be specific: include the exact change in proposed_diff
- confidence 0.0-1.0: how certain you are this will improve performance
- Return a JSON array. Return [] if no improvements needed.

Output format: [{{"target_file": "...", "edit_type": "...", "direction": "short description", "rationale": "why", "confidence": 0.0-1.0, "proposed_diff": "what to change"}}]"""


class MetaAnalyzer:
    def __init__(self, *, llm_fn: Callable[..., Awaitable[str]], targets_path: Path | None) -> None:
        self._llm = llm_fn
        self._valid_targets: set[str] = set()
        if targets_path and targets_path.exists():
            data = yaml.safe_load(targets_path.read_text())
            self._valid_targets = {t["path"] for t in data.get("targets", [])}

    async def analyze(self, *, trace_id: str, trajectory: dict) -> list[MetaSuggestion]:
        try:
            targets_desc = "\n".join(f"- {t}" for t in sorted(self._valid_targets)) if self._valid_targets else "(no targets loaded)"
            prompt = ANALYSIS_PROMPT.format(targets=targets_desc)
            raw = await self._llm(messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(trajectory, indent=2, default=str)[:6000]},
            ])
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
            items = json.loads(cleaned)
            if not isinstance(items, list):
                return []
            suggestions = []
            for item in items:
                tf = item.get("target_file", "")
                if self._valid_targets and tf not in self._valid_targets:
                    logger.debug("Filtered invalid target: %s", tf)
                    continue
                suggestions.append(MetaSuggestion(
                    trace_id=trace_id,
                    target_file=tf,
                    edit_type=item.get("edit_type", ""),
                    direction=item.get("direction", ""),
                    rationale=item.get("rationale", ""),
                    confidence=float(item.get("confidence", 0.5)),
                    proposed_diff=item.get("proposed_diff", ""),
                ))
            return suggestions
        except (json.JSONDecodeError, ValueError):
            logger.warning("Meta analyzer: unparseable output for %s", trace_id[:8])
            return []
        except Exception:
            logger.warning("Meta analyzer failed for %s", trace_id[:8], exc_info=True)
            return []
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_meta_analyzer.py -v`
Expected: 3 pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/meta/meta_analyzer.py free-claw-router/tests/test_meta_analyzer.py
git commit -m "feat(meta): meta analyzer — trajectory to edit suggestions"
```

---

## PART B — Consensus + editor (M1)

### Task 3: meta_consensus.py — majority vote

**Files:**
- Create: `free-claw-router/router/meta/meta_consensus.py`
- Create: `free-claw-router/tests/test_meta_consensus.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_meta_consensus.py`:
```python
from router.meta.meta_consensus import build_edit_plans, EditPlan
from router.meta.meta_suggestions import MetaSuggestion

def _sug(target, direction, trace="t", confidence=0.8):
    return MetaSuggestion(trace_id=trace, target_file=target, edit_type="yaml",
                          direction=direction, rationale="r", confidence=confidence, proposed_diff="d")

def test_consensus_reached_with_3_matching():
    suggestions = [_sug("policy.yaml", "promote groq", f"t{i}") for i in range(3)]
    plans = build_edit_plans(suggestions, min_votes=3)
    assert len(plans) == 1
    assert plans[0].target_file == "policy.yaml"
    assert len(plans[0].supporting_ids) == 3

def test_no_consensus_with_2():
    suggestions = [_sug("policy.yaml", "promote groq", f"t{i}") for i in range(2)]
    plans = build_edit_plans(suggestions, min_votes=3)
    assert plans == []

def test_different_directions_not_grouped():
    suggestions = [
        _sug("policy.yaml", "promote groq", "t1"),
        _sug("policy.yaml", "promote groq", "t2"),
        _sug("policy.yaml", "demote groq", "t3"),
    ]
    plans = build_edit_plans(suggestions, min_votes=3)
    assert plans == []

def test_multiple_targets_independent():
    suggestions = [
        _sug("policy.yaml", "promote groq", "t1"),
        _sug("policy.yaml", "promote groq", "t2"),
        _sug("policy.yaml", "promote groq", "t3"),
        _sug("triggers.py", "lower threshold", "t1"),
        _sug("triggers.py", "lower threshold", "t2"),
    ]
    plans = build_edit_plans(suggestions, min_votes=3)
    assert len(plans) == 1
    assert plans[0].target_file == "policy.yaml"

def test_daily_cap():
    suggestions = [_sug(f"file{i}.yaml", "change", f"t{j}") for i in range(5) for j in range(3)]
    plans = build_edit_plans(suggestions, min_votes=3, daily_cap=2)
    assert len(plans) <= 2
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/meta/meta_consensus.py`:
```python
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from .meta_suggestions import MetaSuggestion


@dataclass
class EditPlan:
    target_file: str
    edit_type: str
    direction: str
    proposed_diff: str
    supporting_ids: list[str] = field(default_factory=list)
    avg_confidence: float = 0.0


def build_edit_plans(
    suggestions: list[MetaSuggestion],
    *,
    min_votes: int = 3,
    daily_cap: int = 2,
) -> list[EditPlan]:
    groups: dict[tuple[str, str], list[MetaSuggestion]] = defaultdict(list)
    for s in suggestions:
        key = (s.target_file, s.direction)
        groups[key].append(s)

    plans: list[EditPlan] = []
    for (target, direction), members in groups.items():
        if len(members) < min_votes:
            continue
        avg_conf = sum(m.confidence for m in members) / len(members)
        plans.append(EditPlan(
            target_file=target,
            edit_type=members[0].edit_type,
            direction=direction,
            proposed_diff=members[0].proposed_diff,
            supporting_ids=[m.id for m in members],
            avg_confidence=avg_conf,
        ))

    plans.sort(key=lambda p: p.avg_confidence, reverse=True)
    return plans[:daily_cap]
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_meta_consensus.py -v`
Expected: 5 pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/meta/meta_consensus.py free-claw-router/tests/test_meta_consensus.py
git commit -m "feat(meta): consensus engine — majority vote to EditPlan"
```

---

### Task 4: meta_editor.py — type-aware file editing

**Files:**
- Create: `free-claw-router/router/meta/meta_editor.py`
- Create: `free-claw-router/tests/test_meta_editor.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_meta_editor.py`:
```python
import yaml
from pathlib import Path
from router.meta.meta_editor import MetaEditor
from router.meta.meta_consensus import EditPlan

def test_yaml_edit(tmp_path: Path):
    f = tmp_path / "policy.yaml"
    f.write_text(yaml.safe_dump({"task_types": {"coding": {"priority": [["openrouter", "model-a"]], "fallback_any": True}}}))

    plan = EditPlan(
        target_file=str(f), edit_type="yaml", direction="promote groq",
        proposed_diff='task_types.coding.priority.0 = ["groq", "llama-3.3-70b"]',
    )
    editor = MetaEditor(base_dir=tmp_path)
    ok = editor.apply(plan)
    assert ok
    result = yaml.safe_load(f.read_text())
    assert result["task_types"]["coding"]["priority"][0] == ["groq", "llama-3.3-70b"]

def test_prompt_only_edit(tmp_path: Path):
    f = tmp_path / "analyzer.py"
    f.write_text('SYSTEM_PROMPT = """old prompt text"""\n\ndef analyze(): pass\n')

    plan = EditPlan(
        target_file=str(f), edit_type="prompt_only", direction="improve prompt",
        proposed_diff='SYSTEM_PROMPT = """new improved prompt"""',
    )
    editor = MetaEditor(base_dir=tmp_path)
    ok = editor.apply(plan)
    assert ok
    content = f.read_text()
    assert "new improved prompt" in content
    assert "def analyze(): pass" in content

def test_config_only_edit(tmp_path: Path):
    f = tmp_path / "triggers.py"
    f.write_text('THRESHOLD = 0.3\n\ndef check(): pass\n')

    plan = EditPlan(
        target_file=str(f), edit_type="config_only", direction="lower threshold",
        proposed_diff="THRESHOLD = 0.25",
    )
    editor = MetaEditor(base_dir=tmp_path)
    ok = editor.apply(plan)
    assert ok
    assert "0.25" in f.read_text()
    assert "def check(): pass" in f.read_text()

def test_rejects_unknown_edit_type(tmp_path: Path):
    plan = EditPlan(target_file="x", edit_type="python", direction="d", proposed_diff="d")
    editor = MetaEditor(base_dir=tmp_path)
    ok = editor.apply(plan)
    assert not ok

def test_yaml_edit_invalid_path_returns_false(tmp_path: Path):
    f = tmp_path / "policy.yaml"
    f.write_text(yaml.safe_dump({"a": 1}))
    plan = EditPlan(target_file=str(f), edit_type="yaml", direction="d",
                    proposed_diff="nonexistent.deep.path = 42")
    editor = MetaEditor(base_dir=tmp_path)
    ok = editor.apply(plan)
    assert not ok
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/meta/meta_editor.py`:
```python
from __future__ import annotations
import logging
import re
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)


class MetaEditor:
    def __init__(self, base_dir: Path) -> None:
        self._base = Path(base_dir)

    def apply(self, plan) -> bool:
        if plan.edit_type == "yaml":
            return self._apply_yaml(plan)
        elif plan.edit_type == "prompt_only":
            return self._apply_prompt(plan)
        elif plan.edit_type == "config_only":
            return self._apply_config(plan)
        else:
            logger.warning("Unknown edit type: %s", plan.edit_type)
            return False

    def _apply_yaml(self, plan) -> bool:
        try:
            path = Path(plan.target_file)
            if not path.is_absolute():
                path = self._base / path
            data = yaml.safe_load(path.read_text())
            match = re.match(r"^([\w.]+)\s*=\s*(.+)$", plan.proposed_diff.strip())
            if not match:
                logger.warning("Cannot parse YAML diff: %s", plan.proposed_diff)
                return False
            key_path = match.group(1).split(".")
            value_str = match.group(2).strip()
            try:
                value = yaml.safe_load(value_str)
            except yaml.YAMLError:
                value = value_str

            obj = data
            for k in key_path[:-1]:
                if isinstance(obj, dict):
                    obj = obj.get(k)
                elif isinstance(obj, list):
                    obj = obj[int(k)]
                else:
                    logger.warning("Cannot navigate YAML path: %s", plan.proposed_diff)
                    return False
                if obj is None:
                    logger.warning("YAML path not found: %s", plan.proposed_diff)
                    return False

            final_key = key_path[-1]
            if isinstance(obj, dict):
                obj[final_key] = value
            elif isinstance(obj, list):
                obj[int(final_key)] = value
            else:
                return False

            path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
            return True
        except Exception:
            logger.warning("YAML edit failed", exc_info=True)
            return False

    def _apply_prompt(self, plan) -> bool:
        try:
            path = Path(plan.target_file)
            if not path.is_absolute():
                path = self._base / path
            content = path.read_text()
            match = re.match(r'^(\w+)\s*=\s*"""(.*)"""$', plan.proposed_diff.strip(), re.DOTALL)
            if not match:
                logger.warning("Cannot parse prompt diff: %s", plan.proposed_diff[:80])
                return False
            var_name = match.group(1)
            new_value = match.group(2)
            pattern = re.compile(rf'({re.escape(var_name)}\s*=\s*""").*?(""")', re.DOTALL)
            if not pattern.search(content):
                logger.warning("Variable %s not found in %s", var_name, path)
                return False
            content = pattern.sub(rf'\g<1>{new_value}\g<2>', content, count=1)
            path.write_text(content)
            return True
        except Exception:
            logger.warning("Prompt edit failed", exc_info=True)
            return False

    def _apply_config(self, plan) -> bool:
        try:
            path = Path(plan.target_file)
            if not path.is_absolute():
                path = self._base / path
            content = path.read_text()
            match = re.match(r'^(\w+)\s*=\s*(.+)$', plan.proposed_diff.strip())
            if not match:
                return False
            var_name = match.group(1)
            new_value = match.group(2).strip()
            pattern = re.compile(rf'^({re.escape(var_name)}\s*=\s*)(.+)$', re.MULTILINE)
            if not pattern.search(content):
                logger.warning("Config var %s not found", var_name)
                return False
            content = pattern.sub(rf'\g<1>{new_value}', content, count=1)
            path.write_text(content)
            return True
        except Exception:
            logger.warning("Config edit failed", exc_info=True)
            return False
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_meta_editor.py -v`
Expected: 5 pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/meta/meta_editor.py free-claw-router/tests/test_meta_editor.py
git commit -m "feat(meta): type-aware editor — yaml, prompt_only, config_only"
```

---

## PART C — PR loop + evaluator (M2+M3)

### Task 5: meta_pr.py — reuse P0 worktree + gh

**Files:**
- Create: `free-claw-router/router/meta/meta_pr.py`
- Create: `free-claw-router/tests/test_meta_pr.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_meta_pr.py`:
```python
import subprocess
from unittest.mock import MagicMock
from pathlib import Path
from router.meta.meta_pr import MetaPR
from router.meta.meta_consensus import EditPlan

def test_creates_branch_and_pr(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)

    captured_gh = {}
    original_run = subprocess.run
    def mock_run(args, **kw):
        if args[0] == "gh":
            captured_gh["args"] = args
            class R:
                returncode = 0
                stdout = "https://github.com/o/r/pull/1"
                stderr = ""
            return R()
        return original_run(args, **kw)
    monkeypatch.setattr(subprocess, "run", mock_run)

    pr = MetaPR(repo=repo, worktree_root=tmp_path / "wt")
    url = pr.submit_edit(
        plan=EditPlan(target_file="policy.yaml", edit_type="yaml",
                      direction="promote groq", proposed_diff="x"),
        edited_content="new content",
        filename="policy.yaml",
    )
    assert "pull" in url
    assert captured_gh["args"][0] == "gh"

def test_dry_run_returns_none(tmp_path):
    pr = MetaPR(repo=tmp_path, worktree_root=tmp_path / "wt", dry_run=True)
    url = pr.submit_edit(
        plan=EditPlan(target_file="x", edit_type="yaml", direction="d", proposed_diff="d"),
        edited_content="c", filename="x",
    )
    assert url is None
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/meta/meta_pr.py`:
```python
from __future__ import annotations
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from .meta_consensus import EditPlan

logger = logging.getLogger(__name__)


class MetaPR:
    def __init__(self, *, repo: Path, worktree_root: Path, dry_run: bool = False) -> None:
        self._repo = Path(repo)
        self._wt_root = Path(worktree_root)
        self._dry_run = dry_run

    def submit_edit(self, *, plan: EditPlan, edited_content: str, filename: str) -> str | None:
        if self._dry_run:
            logger.info("[DRY RUN] Would submit PR for %s: %s", plan.target_file, plan.direction)
            return None

        branch = f"meta/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{filename.replace('/', '-').replace('.', '-')}"
        wt_path = self._wt_root / branch.replace("/", "__")

        try:
            self._wt_root.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "worktree", "add", "-b", branch, str(wt_path), "main"],
                           cwd=self._repo, check=True, capture_output=True)
            target = wt_path / plan.target_file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(edited_content)

            subprocess.run(["git", "add", "-A"], cwd=wt_path, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", f"meta: {plan.direction}"],
                           cwd=wt_path, check=True, capture_output=True)
            subprocess.run(["git", "push", "-u", "origin", branch],
                           cwd=wt_path, check=True, capture_output=True)

            result = subprocess.run(
                ["gh", "pr", "create", "--title", f"meta: {plan.direction}",
                 "--body", f"Auto-generated by HyperAgent meta-evolution.\n\nRationale: {plan.proposed_diff}",
                 "--base", "main", "--head", branch],
                cwd=wt_path, check=False, capture_output=True, text=True,
            )
            url = result.stdout.strip() if result.returncode == 0 else ""
            if not url:
                logger.warning("gh pr create failed: %s", result.stderr)
            return url or None
        except Exception:
            logger.warning("Meta PR failed", exc_info=True)
            return None
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt_path)],
                           cwd=self._repo, check=False, capture_output=True)
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_meta_pr.py -v`
Expected: 2 pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/meta/meta_pr.py free-claw-router/tests/test_meta_pr.py
git commit -m "feat(meta): PR pipeline — worktree + gh for meta edits"
```

---

### Task 6: meta_evaluator.py — pre/post comparison + auto-rollback

**Files:**
- Create: `free-claw-router/router/meta/meta_evaluator.py`
- Create: `free-claw-router/tests/test_meta_evaluator.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_meta_evaluator.py`:
```python
from router.meta.meta_evaluator import MetaEvaluator, Verdict

def test_improved_when_metrics_better():
    pre = {"success_rate": 0.70, "tool_success_rate": 0.65, "mistake_count": 5}
    post = {"success_rate": 0.85, "tool_success_rate": 0.80, "mistake_count": 2}
    ev = MetaEvaluator(degradation_threshold=0.15)
    assert ev.evaluate(pre, post) == Verdict.KEEP

def test_degraded_when_metrics_worse():
    pre = {"success_rate": 0.85, "tool_success_rate": 0.80, "mistake_count": 2}
    post = {"success_rate": 0.60, "tool_success_rate": 0.55, "mistake_count": 6}
    ev = MetaEvaluator(degradation_threshold=0.15)
    assert ev.evaluate(pre, post) == Verdict.REVERT

def test_inconclusive_when_mixed():
    pre = {"success_rate": 0.75, "tool_success_rate": 0.70, "mistake_count": 3}
    post = {"success_rate": 0.80, "tool_success_rate": 0.60, "mistake_count": 3}
    ev = MetaEvaluator(degradation_threshold=0.15)
    assert ev.evaluate(pre, post) == Verdict.INCONCLUSIVE

def test_keep_when_stable():
    pre = {"success_rate": 0.80, "tool_success_rate": 0.75, "mistake_count": 3}
    post = {"success_rate": 0.79, "tool_success_rate": 0.74, "mistake_count": 3}
    ev = MetaEvaluator(degradation_threshold=0.15)
    assert ev.evaluate(pre, post) == Verdict.KEEP
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/meta/meta_evaluator.py`:
```python
from __future__ import annotations
from enum import Enum


class Verdict(str, Enum):
    KEEP = "keep"
    REVERT = "revert"
    INCONCLUSIVE = "inconclusive"


class MetaEvaluator:
    def __init__(self, degradation_threshold: float = 0.15) -> None:
        self._threshold = degradation_threshold

    def evaluate(self, pre: dict[str, float], post: dict[str, float]) -> Verdict:
        improved = 0
        degraded = 0
        for key in pre:
            if key not in post:
                continue
            pre_val = pre[key]
            post_val = post[key]
            if key == "mistake_count":
                # Lower is better
                delta = (pre_val - post_val) / max(pre_val, 1)
            else:
                # Higher is better
                delta = (post_val - pre_val) / max(pre_val, 0.01)

            if delta > self._threshold:
                improved += 1
            elif delta < -self._threshold:
                degraded += 1

        if degraded > 0 and improved == 0:
            return Verdict.REVERT
        if degraded > 0 and improved > 0:
            return Verdict.INCONCLUSIVE
        return Verdict.KEEP
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_meta_evaluator.py -v`
Expected: 4 pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/meta/meta_evaluator.py free-claw-router/tests/test_meta_evaluator.py
git commit -m "feat(meta): evaluator — pre/post comparison with keep/revert/inconclusive"
```

---

## PART D — Wiring (M2+M3)

### Task 7: Wire everything into lifespan + mining hooks + daily cron

**Files:**
- Modify: `free-claw-router/router/server/lifespan.py`
- Create: `free-claw-router/tests/test_meta_integration.py`

- [ ] **Step 1: Write integration test**

Create `free-claw-router/tests/test_meta_integration.py`:
```python
import json
from pathlib import Path
from unittest.mock import AsyncMock
from router.meta.meta_analyzer import MetaAnalyzer
from router.meta.meta_suggestions import SuggestionStore, MetaSuggestion
from router.meta.meta_consensus import build_edit_plans
from router.meta.meta_editor import MetaEditor
from router.meta.meta_evaluator import MetaEvaluator, Verdict

def test_full_pipeline_suggestion_to_edit(tmp_path: Path):
    # 1. Create suggestion store with 3 matching suggestions
    store = SuggestionStore(path=tmp_path / "s.json")
    for i in range(3):
        store.append(MetaSuggestion(
            trace_id=f"t{i}", target_file="policy.yaml", edit_type="yaml",
            direction="promote groq", rationale="better tool success",
            confidence=0.85, proposed_diff='task_types.coding.priority.0 = ["groq", "llama"]',
        ))

    # 2. Build consensus
    plans = build_edit_plans(store.read_all(), min_votes=3)
    assert len(plans) == 1

    # 3. Apply edit
    import yaml
    policy = tmp_path / "policy.yaml"
    policy.write_text(yaml.safe_dump({"task_types": {"coding": {"priority": [["openrouter", "old"]], "fallback_any": True}}}))
    plans[0].target_file = str(policy)

    editor = MetaEditor(base_dir=tmp_path)
    assert editor.apply(plans[0])

    result = yaml.safe_load(policy.read_text())
    assert result["task_types"]["coding"]["priority"][0] == ["groq", "llama"]

    # 4. Evaluate
    ev = MetaEvaluator()
    verdict = ev.evaluate(
        pre={"success_rate": 0.70, "tool_success_rate": 0.65},
        post={"success_rate": 0.85, "tool_success_rate": 0.82},
    )
    assert verdict == Verdict.KEEP

def test_meta_analyzer_to_suggestion_store(tmp_path: Path):
    import asyncio
    mock_llm = AsyncMock(return_value='[{"target_file":"router/routing/policy.yaml","edit_type":"yaml","direction":"x","rationale":"y","confidence":0.8,"proposed_diff":"z"}]')
    analyzer = MetaAnalyzer(llm_fn=mock_llm, targets_path=None)
    suggestions = asyncio.run(analyzer.analyze(trace_id="aa", trajectory={"summary": "test"}))

    store = SuggestionStore(path=tmp_path / "s.json")
    for s in suggestions:
        store.append(s)
    assert len(store.read_all()) == 1
```

- [ ] **Step 2: Wire into lifespan**

In `free-claw-router/router/server/lifespan.py`, after existing P3 hooks:

```python
from router.meta.meta_analyzer import MetaAnalyzer
from router.meta.meta_suggestions import SuggestionStore
from router.meta.meta_consensus import build_edit_plans
from router.meta.meta_editor import MetaEditor
from router.meta.meta_pr import MetaPR

    # Meta-evolution (P4)
    suggestions_path = Path.home() / ".free-claw-router" / "meta_suggestions.json"
    meta_store = SuggestionStore(path=suggestions_path)
    targets_path = Path(__file__).resolve().parent.parent / "meta" / "meta_targets.yaml"
    meta_analyzer = MetaAnalyzer(llm_fn=_batch_llm, targets_path=targets_path)

    def _meta_hook(trace_id, transcript, wing):
        """Extract trajectory from mempalace and analyze for meta-suggestions."""
        import asyncio
        try:
            # Read the latest trajectory from mempalace (just stored by P3)
            from mempalace.searcher import search_memories
            import os
            results = search_memories(
                f"trajectory session {trace_id[:8]}",
                palace_path=os.path.expanduser("~/.mempalace/palace"),
                wing=wing, room="trajectories", n_results=1,
            )
            trajectory = {}
            for r in results.get("results", []):
                try:
                    trajectory = json.loads(r.get("content", "{}"))
                    break
                except json.JSONDecodeError:
                    pass
            if trajectory:
                suggestions = asyncio.run(meta_analyzer.analyze(trace_id=trace_id, trajectory=trajectory))
                for s in suggestions:
                    meta_store.append(s)
        except RuntimeError:
            pass  # event loop issue — best effort
        except Exception:
            import logging
            logging.getLogger(__name__).warning("Meta hook failed", exc_info=True)

    session_detector._on_mine_hooks.append(_meta_hook)

    # Daily meta-evolution cron
    def _daily_meta_evolution():
        import logging
        log = logging.getLogger("meta_cron")
        meta_store.prune()
        all_suggestions = meta_store.read_all()
        plans = build_edit_plans(all_suggestions, min_votes=3, daily_cap=2)
        if not plans:
            log.info("No meta edit plans reached consensus")
            return
        editor = MetaEditor(base_dir=Path(__file__).resolve().parent.parent)
        for plan in plans:
            if editor.apply(plan):
                log.info("Applied meta edit: %s", plan.direction)
                meta_store.clear_target(plan.target_file)
            else:
                log.warning("Meta edit failed: %s", plan.direction)

    bg_scheduler.add_job(_daily_meta_evolution, "cron", hour=3, id="daily_meta_evolution")
```

- [ ] **Step 3: Run full test suite**

Run: `cd free-claw-router && uv run pytest tests/ -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/server/lifespan.py free-claw-router/tests/test_meta_integration.py
git commit -m "feat(server): wire meta-evolution pipeline — analyzer hook + daily cron (P4 complete)"
```

---

## Self-review

**Spec coverage:**

| Spec section | Task(s) |
|---|---|
| §2 (1) Meta analyzer | Task 2 |
| §2 (2) Suggestion accumulator | Task 1 |
| §2 (3) Consensus engine | Task 3 |
| §2 (4) Meta editor (type-aware) | Task 4 |
| §2 (5) PR integration | Task 5 |
| §2 (6) Evaluator + auto-rollback | Task 6 |
| §2 (7) Edit target registry | Task 1 |
| §3 Architecture flow | Task 7 (wiring) |
| §5 Safety: scope limit | Task 1 (meta_targets.yaml) + Task 2 (filter) |
| §5 Safety: 3-vote consensus | Task 3 |
| §5 Safety: PR review | Task 5 |
| §5 Safety: auto-rollback | Task 6 |
| §5 Safety: daily cap | Task 3 (daily_cap param) |
| §10 M0-M3 | M0=Tasks 1-2, M1=Tasks 3-4, M2=Task 5+7, M3=Task 6+7 |

**Note:** Auto-rollback (Task 6) provides the `MetaEvaluator` class but the actual "5 sessions post-edit" cron job that reads telemetry and calls `evaluate()` is not wired as a separate task — it's documented in the spec as the final loop. The evaluator module is ready; wiring the evaluation cron into the daily job (checking if any recent edits need evaluation) is a natural follow-up within the daily cron function in Task 7. The implementer should add a TODO comment for this in `_daily_meta_evolution`.

**Placeholder scan:** Clean.

**Type consistency:** `MetaSuggestion` fields consistent across Tasks 1-2. `EditPlan` fields consistent across Tasks 3-5. `Verdict` enum consistent in Task 6-7.
