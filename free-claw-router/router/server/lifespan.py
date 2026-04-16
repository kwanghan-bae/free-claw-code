from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from router.telemetry.store import Store
from router.catalog.hot_reload import CatalogLive
from router.memory.wakeup import WakeupService
from router.memory.injector import Injector

DEFAULT_DB = Path.home() / ".free-claw-router" / "telemetry.db"
DATA_DIR = Path(__file__).resolve().parent.parent / "catalog" / "data"

@asynccontextmanager
async def lifespan(app: FastAPI):
    DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
    store = Store(path=DEFAULT_DB)
    store.initialize()
    live = CatalogLive(DATA_DIR)
    live.start()
    wakeup_svc = WakeupService(ttl_seconds=300)
    injector = Injector(wakeup_fn=wakeup_svc.get_wakeup, idle_threshold_seconds=1800)

    app.state.telemetry_store = store
    app.state.catalog_live = live
    app.state.catalog_version = live.snapshot().version
    app.state.wakeup_service = wakeup_svc
    app.state.injector = injector
    try:
        yield
    finally:
        live.stop()
