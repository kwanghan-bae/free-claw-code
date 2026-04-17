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
        if args[0] == "git" and len(args) > 1 and args[1] == "push":
            class R:
                returncode = 0
                stdout = b""
                stderr = b""
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
