import json
from pathlib import Path
from jsonschema import Draft202012Validator

SCHEMA = Path(__file__).resolve().parent.parent / "ops" / "catalog-schema.json"

def test_schema_is_valid_draft_2020_12():
    data = json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(data)

def test_valid_research_payload_accepted():
    data = json.loads(SCHEMA.read_text())
    validator = Draft202012Validator(data)
    payload = {
        "provider_id": "openrouter",
        "model_id": "test/m:free",
        "status": "added",
        "context_window": 8192,
        "tool_use": True,
        "structured_output": "partial",
        "free_tier": {"rpm": 10, "tpm": 5000, "daily": None, "reset_policy": "minute"},
        "pricing": {"input": 0, "output": 0, "free": True},
        "quirks": [],
        "evidence_urls": ["https://openrouter.ai/models/test/m:free"],
    }
    errors = list(validator.iter_errors(payload))
    assert errors == []

def test_missing_evidence_rejected():
    data = json.loads(SCHEMA.read_text())
    validator = Draft202012Validator(data)
    payload = {
        "provider_id": "openrouter",
        "model_id": "test/m:free",
        "status": "added",
        "context_window": 8192,
        "tool_use": True,
        "structured_output": "partial",
        "free_tier": {"rpm": 10, "tpm": 5000, "daily": None, "reset_policy": "minute"},
        "pricing": {"input": 0, "output": 0, "free": True},
        "quirks": [],
        "evidence_urls": [],
    }
    errors = list(validator.iter_errors(payload))
    assert len(errors) > 0
