import time
from pathlib import Path
from router.catalog.hot_reload import CatalogLive

YAML_TEMPLATE = """\
provider_id: {pid}
base_url: https://x
auth: {{env: K, scheme: bearer}}
known_ratelimit_header_schema: generic
models:
  - model_id: {pid}/m:free
    status: active
    context_window: 8000
    tool_use: false
    structured_output: none
    free_tier: {{rpm: 10, tpm: 5000, daily: null, reset_policy: minute}}
    pricing: {{input: 0, output: 0, free: true}}
    quirks: []
    evidence_urls: [https://x/m]
    last_verified: "2026-04-15T00:00:00Z"
    first_seen: "2026-04-15"
"""

def test_live_catalog_swaps_on_file_change(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "one.yaml").write_text(YAML_TEMPLATE.format(pid="one"))
    live = CatalogLive(data)
    live.start()
    try:
        assert live.snapshot().providers[0].provider_id == "one"
        (data / "one.yaml").write_text(YAML_TEMPLATE.format(pid="one-v2"))
        for _ in range(50):
            if live.snapshot().providers[0].provider_id == "one-v2":
                break
            time.sleep(0.05)
        assert live.snapshot().providers[0].provider_id == "one-v2"
    finally:
        live.stop()
