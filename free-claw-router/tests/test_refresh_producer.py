import json
from pathlib import Path
import subprocess
from router.catalog.refresh.producer import Producer, ProducerResult

def test_producer_dry_run_writes_yaml(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)

    catalog_dir = repo / "catalog" / "data"
    catalog_dir.mkdir(parents=True)

    research = [{
        "provider_id": "openrouter",
        "model_id": "test/model:free",
        "status": "added",
        "context_window": 4096,
        "tool_use": False,
        "structured_output": "none",
        "free_tier": {"rpm": 5, "tpm": 1000, "daily": None, "reset_policy": "minute"},
        "pricing": {"input": 0, "output": 0, "free": True},
        "quirks": [],
        "evidence_urls": ["https://openrouter.ai/models/test/model:free"],
    }]
    rpath = repo / "research.json"
    rpath.write_text(json.dumps(research))

    p = Producer(repo=repo, worktree_root=tmp_path / "wt", catalog_dir=catalog_dir, dry_run=True)
    result = p.run_for_provider("openrouter", research_json=rpath)
    assert isinstance(result, ProducerResult)
    assert result.dry_run is True
    assert result.new_yaml_path.exists()
    content = result.new_yaml_path.read_text()
    assert "test/model:free" in content
