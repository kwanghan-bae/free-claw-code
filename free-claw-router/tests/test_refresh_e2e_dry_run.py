import json
from pathlib import Path
import subprocess
from router.catalog.refresh.producer import Producer

def test_dry_run_refresh_writes_yaml_and_passes_schema(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
    catalog_dir = repo / "catalog" / "data"
    catalog_dir.mkdir(parents=True)

    research = [{
        "provider_id": "openrouter",
        "model_id": "z-ai/glm-4.6:free",
        "status": "added",
        "context_window": 131072,
        "tool_use": True,
        "structured_output": "partial",
        "free_tier": {"rpm": 20, "tpm": 100000, "daily": None, "reset_policy": "minute"},
        "pricing": {"input": 0, "output": 0, "free": True},
        "quirks": [],
        "evidence_urls": ["https://openrouter.ai/models/z-ai/glm-4.6:free"],
    }]
    rpath = repo / "research.json"
    rpath.write_text(json.dumps(research))

    p = Producer(repo=repo, worktree_root=tmp_path / "wt",
                 catalog_dir=catalog_dir, dry_run=True)
    result = p.run_for_provider("openrouter", research_json=rpath)
    assert result.dry_run is True
    assert result.new_yaml_path.exists()
    assert "z-ai/glm-4.6:free" in result.new_yaml_path.read_text()
