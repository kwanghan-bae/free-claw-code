from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from router.telemetry.store import Store

DEFAULT_DB = Path.home() / ".free-claw-router" / "telemetry.db"

@asynccontextmanager
async def lifespan(app: FastAPI):
    DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
    store = Store(path=DEFAULT_DB)
    store.initialize()
    app.state.telemetry_store = store
    app.state.catalog_version = "unversioned"
    yield
