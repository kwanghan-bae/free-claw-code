from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml
from router.catalog.schema import ProviderSpec, ModelSpec

@dataclass
class Registry:
    providers: list[ProviderSpec]
    version: str

    @classmethod
    def load_from_dir(cls, path: Path) -> "Registry":
        providers: list[ProviderSpec] = []
        latest_verified = ""
        for yml in sorted(Path(path).glob("*.yaml")):
            data = yaml.safe_load(yml.read_text())
            p = ProviderSpec.model_validate(data).validate_unique_models()
            providers.append(p)
            for m in p.models:
                if m.last_verified > latest_verified:
                    latest_verified = m.last_verified
        version = latest_verified.split("T", 1)[0] if latest_verified else "unknown"
        return cls(providers=providers, version=version)

    def find_model(self, model_id: str) -> tuple[ProviderSpec, ModelSpec] | None:
        for p in self.providers:
            for m in p.models:
                if m.model_id == model_id:
                    return (p, m)
        return None

    def find_models_for(
        self,
        *,
        task_type: str | None = None,
        min_context: int = 0,
        require_tool_use: bool | None = None,
    ) -> list[tuple[ProviderSpec, ModelSpec]]:
        requires_tools = (
            require_tool_use
            if require_tool_use is not None
            else task_type == "tool_heavy"
        )
        out: list[tuple[ProviderSpec, ModelSpec]] = []
        for p in self.providers:
            for m in p.models:
                if m.status != "active":
                    continue
                if m.context_window < min_context:
                    continue
                if requires_tools and not m.tool_use:
                    continue
                out.append((p, m))
        return out
