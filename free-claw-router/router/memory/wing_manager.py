from __future__ import annotations
from pathlib import Path
from router.telemetry.store import Store


class WingManager:
    user_wing: str = "user"

    def __init__(self, store: Store) -> None:
        self._store = store

    def resolve(self, workspace_path: str | None) -> str:
        if not workspace_path or not workspace_path.strip():
            return "default"
        wing = Path(workspace_path.strip()).name
        if not wing:
            return "default"
        self._persist(workspace_path.strip(), wing)
        return wing

    def _persist(self, workspace_path: str, wing_name: str) -> None:
        with self._store.connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO wing_mappings(workspace_path, wing_name) VALUES(?, ?)",
                (workspace_path, wing_name),
            )
