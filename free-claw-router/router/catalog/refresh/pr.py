from __future__ import annotations
import subprocess
from pathlib import Path

class GhError(RuntimeError):
    pass

def _run(args: list[str], cwd: Path) -> str:
    r = subprocess.run(args, cwd=str(cwd), check=False, capture_output=True, text=True)
    if r.returncode != 0:
        raise GhError(f"{' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()

def create_pr(*, cwd: Path, title: str, body: str, base: str, head: str) -> str:
    return _run(["gh", "pr", "create", "--title", title, "--body", body, "--base", base, "--head", head], cwd)

def comment_pr(*, cwd: Path, pr_number: int, body: str) -> None:
    _run(["gh", "pr", "comment", str(pr_number), "--body", body], cwd)
