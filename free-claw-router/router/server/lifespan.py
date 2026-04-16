from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from router.telemetry.store import Store
from router.catalog.hot_reload import CatalogLive

DEFAULT_DB = Path.home() / ".free-claw-router" / "telemetry.db"
DATA_DIR = Path(__file__).resolve().parent.parent / "catalog" / "data"

@asynccontextmanager
async def lifespan(app: FastAPI):
    DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
    store = Store(path=DEFAULT_DB)
    store.initialize()
    live = CatalogLive(DATA_DIR)
    live.start()
    app.state.telemetry_store = store
    app.state.catalog_live = live
    app.state.catalog_version = live.snapshot().version
    try:
        yield
    finally:
        live.stop()
