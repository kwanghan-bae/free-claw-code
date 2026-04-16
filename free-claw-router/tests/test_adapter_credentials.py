from router.adapters.hermes_credentials import resolve_api_key

def test_resolves_from_env(monkeypatch):
    monkeypatch.setenv("FAKE_API_KEY", "sk-xxx")
    assert resolve_api_key(env_name="FAKE_API_KEY") == "sk-xxx"

def test_returns_none_when_missing(monkeypatch):
    monkeypatch.delenv("NOSUCH_KEY", raising=False)
    assert resolve_api_key(env_name="NOSUCH_KEY") is None
