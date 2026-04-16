from pathlib import Path
from router.catalog.registry import Registry

DATA = Path(__file__).resolve().parent.parent / "router" / "catalog" / "data"

def test_openrouter_present_and_all_models_free():
    r = Registry.load_from_dir(DATA)
    names = [p.provider_id for p in r.providers]
    assert "openrouter" in names
    for p in r.providers:
        for m in p.models:
            assert m.pricing.free
