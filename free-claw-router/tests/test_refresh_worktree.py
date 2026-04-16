from pathlib import Path
import subprocess
import pytest
from router.catalog.refresh.worktree import Worktree

def test_create_worktree_isolated(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)

    wt_root = tmp_path / "worktrees"
    wt = Worktree(repo=repo, worktree_root=wt_root, branch="refresh/test", base="main")
    path = wt.create()
    assert path.exists()
    assert (path / ".git").exists()
    wt.remove()
    assert not path.exists()

def test_refuses_existing_branch_without_force(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "refresh/existing"], cwd=repo, check=True)

    wt = Worktree(repo=repo, worktree_root=tmp_path / "w", branch="refresh/existing", base="main")
    with pytest.raises(RuntimeError):
        wt.create()
