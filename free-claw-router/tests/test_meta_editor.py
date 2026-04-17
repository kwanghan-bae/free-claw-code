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
