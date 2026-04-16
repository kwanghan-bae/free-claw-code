from pathlib import Path
from router.catalog.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures" / "catalog" / "sample"

def test_registry_loads_one_provider_from_dir():
    r = Registry.load_from_dir(FIXTURES)
    assert len(r.providers) == 1
    assert r.providers[0].provider_id == "example"

def test_registry_find_by_model_id():
    r = Registry.load_from_dir(FIXTURES)
    spec = r.find_model("example/m1:free")
    assert spec is not None
    prov, model = spec
    assert prov.provider_id == "example"
    assert model.context_window == 8192

def test_registry_filter_by_capability():
    r = Registry.load_from_dir(FIXTURES)
    matches = r.find_models_for(task_type="tool_heavy", min_context=4096)
    assert matches == []

def test_registry_version_is_date_based():
    r = Registry.load_from_dir(FIXTURES)
    assert r.version == "2026-04-15"
