import subprocess
import pytest
from router.catalog.refresh.pr import create_pr, GhError

def test_create_pr_invokes_gh(monkeypatch, tmp_path):
    captured = {}
    def fake_run(args, cwd=None, check=True, capture_output=True, text=True):
        captured["args"] = args
        class R:
            returncode = 0
            stdout = "https://github.com/o/r/pull/7"
            stderr = ""
        return R()
    monkeypatch.setattr(subprocess, "run", fake_run)
    url = create_pr(cwd=tmp_path, title="x", body="y", base="main", head="refresh/foo")
    assert url == "https://github.com/o/r/pull/7"
    assert captured["args"][0:2] == ["gh", "pr"]

def test_create_pr_raises_on_error(monkeypatch, tmp_path):
    class R:
        returncode = 1
        stdout = ""
        stderr = "gh: bad"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    with pytest.raises(GhError):
        create_pr(cwd=tmp_path, title="x", body="y", base="main", head="refresh/foo")
