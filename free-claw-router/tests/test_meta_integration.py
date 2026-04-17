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
