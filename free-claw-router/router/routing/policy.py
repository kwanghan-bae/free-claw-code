from __future__ import annotations
from pathlib import Path
import yaml
from dataclasses import dataclass

@dataclass
class Policy:
    version: str
    rules: dict[str, dict]

    @classmethod
    def load(cls, path: Path) -> "Policy":
        data = yaml.safe_load(Path(path).read_text())
        rules: dict[str, dict] = {}
        for tt, body in data["task_types"].items():
            pri = [tuple(pair) for pair in body["priority"]]
            rules[tt] = {"priority": pri, "fallback_any": bool(body.get("fallback_any", False))}
        return cls(version=str(data["policy_version"]), rules=rules)

    def task_types(self) -> list[str]:
        return list(self.rules.keys())

    def priority_for(self, task_type: str) -> list[tuple[str, str]]:
        return self.rules[task_type]["priority"]

    def fallback_any(self, task_type: str) -> bool:
        return self.rules[task_type]["fallback_any"]
