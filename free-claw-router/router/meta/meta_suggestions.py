from __future__ import annotations
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class MetaSuggestion:
    trace_id: str
    target_file: str
    edit_type: str
    direction: str
    rationale: str
    confidence: float
    proposed_diff: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)


class SuggestionStore:
    def __init__(self, path: Path, max_age_days: int = 7) -> None:
        self._path = Path(path)
        self._max_age = max_age_days * 86400

    def append(self, suggestion: MetaSuggestion) -> None:
        items = self._load()
        items.append(asdict(suggestion))
        self._save(items)

    def read_all(self) -> list[MetaSuggestion]:
        return [MetaSuggestion(**item) for item in self._load()]

    def prune(self) -> None:
        now = time.time()
        items = [i for i in self._load() if now - i.get("timestamp", 0) < self._max_age]
        self._save(items)

    def clear_target(self, target_file: str) -> None:
        items = [i for i in self._load() if i.get("target_file") != target_file]
        self._save(items)

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, items: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(items, indent=2))
