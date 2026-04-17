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
