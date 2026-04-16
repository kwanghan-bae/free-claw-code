from __future__ import annotations
import subprocess
from pathlib import Path

class Worktree:
    def __init__(self, *, repo: Path, worktree_root: Path, branch: str, base: str = "main") -> None:
        self.repo = Path(repo).resolve()
        self.worktree_root = Path(worktree_root).resolve()
        self.branch = branch
        self.base = base
        self.path: Path | None = None

    def _git(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=cwd or self.repo,
            check=check, capture_output=True, text=True)

    def create(self) -> Path:
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        if self._branch_exists():
            raise RuntimeError(f"branch {self.branch} already exists")
        target = self.worktree_root / self.branch.replace("/", "__")
        self._git("worktree", "add", "-b", self.branch, str(target), self.base)
        self.path = target
        return target

    def remove(self) -> None:
        if not self.path:
            return
        self._git("worktree", "remove", "--force", str(self.path), check=False)
        self.path = None

    def _branch_exists(self) -> bool:
        result = self._git("rev-parse", "--verify", self.branch, check=False)
        return result.returncode == 0
