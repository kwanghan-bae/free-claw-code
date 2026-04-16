from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import yaml
import jsonschema
from router.catalog.refresh.worktree import Worktree
from router.catalog.refresh.pr import create_pr

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "ops" / "catalog-schema.json"

@dataclass
class ProducerResult:
    new_yaml_path: Path
    pr_url: str | None
    dry_run: bool

class Producer:
    def __init__(self, *, repo: Path, worktree_root: Path, catalog_dir: Path, dry_run: bool = False) -> None:
        self.repo = repo
        self.worktree_root = worktree_root
        self.catalog_dir = catalog_dir
        self.dry_run = dry_run

    def _validate_research(self, entries: list[dict]) -> None:
        schema = json.loads(SCHEMA_PATH.read_text())
        validator = jsonschema.Draft202012Validator(schema)
        for entry in entries:
            errs = sorted(validator.iter_errors(entry), key=lambda e: list(e.path))
            if errs:
                raise ValueError("research payload failed schema: " + "; ".join(e.message for e in errs))

    def _merge_yaml(self, provider_id: str, entries: list[dict], out: Path) -> None:
        existing = {}
        if out.exists():
            existing = yaml.safe_load(out.read_text()) or {}
        models_by_id = {m["model_id"]: m for m in (existing.get("models") or [])}
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        today = now.split("T", 1)[0]
        for entry in entries:
            entry_wo_meta = {k: v for k, v in entry.items() if k not in ("status",)}
            models_by_id[entry["model_id"]] = {
                **entry_wo_meta,
                "status": "active" if entry["status"] != "deprecated" else "deprecated",
                "last_verified": now,
                "first_seen": models_by_id.get(entry["model_id"], {}).get("first_seen", today),
            }
        doc = {
            "provider_id": provider_id,
            "base_url": existing.get("base_url") or "",
            "auth": existing.get("auth") or {"env": f"{provider_id.upper()}_API_KEY", "scheme": "bearer"},
            "known_ratelimit_header_schema": existing.get("known_ratelimit_header_schema") or "generic",
            "models": list(models_by_id.values()),
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))

    def run_for_provider(self, provider_id: str, *, research_json: Path) -> ProducerResult:
        entries = json.loads(research_json.read_text())
        self._validate_research(entries)
        target = self.catalog_dir / f"{provider_id}.yaml"
        if self.dry_run:
            self._merge_yaml(provider_id, entries, target)
            return ProducerResult(new_yaml_path=target, pr_url=None, dry_run=True)

        branch = f"catalog/refresh/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{provider_id}"
        wt = Worktree(repo=self.repo, worktree_root=self.worktree_root, branch=branch, base="main")
        path = wt.create()
        try:
            import subprocess
            self._merge_yaml(provider_id, entries, path / target.relative_to(self.repo))
            subprocess.run(["git", "add", "-A"], cwd=path, check=True)
            subprocess.run(["git", "commit", "-m", f"catalog: refresh {provider_id}"], cwd=path, check=True)
            subprocess.run(["git", "push", "-u", "origin", branch], cwd=path, check=True)
            pr_url = create_pr(
                cwd=path, title=f"catalog: refresh {provider_id}",
                body="Automated catalog refresh.", base="main", head=branch)
            return ProducerResult(new_yaml_path=target, pr_url=pr_url, dry_run=False)
        finally:
            wt.remove()
