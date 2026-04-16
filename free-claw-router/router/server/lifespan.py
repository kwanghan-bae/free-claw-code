from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from router.telemetry.store import Store
from router.catalog.hot_reload import CatalogLive
from router.memory.wakeup import WakeupService
from router.memory.injector import Injector
from router.memory.miner import MemoryMiner
from router.memory.idle_detector import SessionCloseDetector
from router.memory.transcript import build_transcript
from router.memory.wing_manager import WingManager

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

    wing_mgr = WingManager(store=store)
    mem_miner = MemoryMiner()
    def _transcript_fn(trace_id_hex: str) -> str:
        tid = bytes.fromhex(trace_id_hex) if len(trace_id_hex) == 32 else b""
        return build_transcript(store, trace_id=tid)
    session_detector = SessionCloseDetector(
        close_timeout_seconds=300,
        idle_threshold_seconds=1800,
        miner=mem_miner,
        transcript_fn=_transcript_fn,
        wakeup_invalidate_fn=wakeup_svc.invalidate,
        wing_resolve_fn=lambda ws: wing_mgr.resolve(ws),
    )

    from apscheduler.schedulers.background import BackgroundScheduler
    bg_scheduler = BackgroundScheduler()
    bg_scheduler.add_job(session_detector.check_and_mine, "interval", seconds=60, id="session_close_check")
    bg_scheduler.start()

    app.state.telemetry_store = store
    app.state.catalog_live = live
    app.state.catalog_version = live.snapshot().version
    app.state.wakeup_service = wakeup_svc
    app.state.injector = injector
    app.state.session_detector = session_detector
    app.state.wing_manager = wing_mgr
    try:
        yield
    finally:
        bg_scheduler.shutdown(wait=False)
        live.stop()
