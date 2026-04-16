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
from router.skills.bridge import SkillsBridge
from router.skills.analyzer_hook import AnalyzerHook
from router.skills.adapter import build_analysis_context
from router.skills.triggers import register_trigger_jobs
from router.learning.nudge_cache import NudgeCache, ConversationBuffer
from router.learning.rule_detector import RuleDetector
from router.learning.nudge_injector import NudgeInjector
from router.learning.batch_analyzer import BatchAnalyzer
from router.dispatch.client import DispatchClient

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

    # Skills (P2)
    skills_bridge = SkillsBridge()
    skills_bridge.initialize()

    analyzer_hook = AnalyzerHook(
        bridge=skills_bridge,
        build_context_fn=build_analysis_context,
        telemetry_store=store,
    )

    # Register analyzer as a mining hook
    session_detector._on_mine_hooks.append(analyzer_hook.on_session_mined)

    # Learning (P3)
    nudge_cache = NudgeCache()
    conv_buffer = ConversationBuffer()
    rule_detector = RuleDetector()
    nudge_injector = NudgeInjector(cache=nudge_cache)

    async def _batch_llm(messages, model=None):
        """Route LLM calls through our own dispatch (loopback)."""
        snapshot = live.snapshot()
        provider = None
        model_spec = None
        for p in snapshot.providers:
            for m in p.models:
                if m.status == "active":
                    provider = p
                    model_spec = m
                    break
            if provider:
                break
        if not provider or not model_spec:
            return ""
        result = await DispatchClient().call(
            provider, model_spec,
            {"messages": messages},
            {"x-free-claw-hints": "summary"},
        )
        return result.body.get("choices", [{}])[0].get("message", {}).get("content", "")

    batch_analyzer = BatchAnalyzer(llm_fn=_batch_llm)

    from apscheduler.schedulers.background import BackgroundScheduler
    bg_scheduler = BackgroundScheduler()
    bg_scheduler.add_job(session_detector.check_and_mine, "interval", seconds=60, id="session_close_check")

    # Register periodic trigger jobs
    register_trigger_jobs(bg_scheduler, telemetry_store=store, skill_bridge=skills_bridge)

    bg_scheduler.start()

    app.state.telemetry_store = store
    app.state.catalog_live = live
    app.state.catalog_version = live.snapshot().version
    app.state.wakeup_service = wakeup_svc
    app.state.injector = injector
    app.state.session_detector = session_detector
    app.state.wing_manager = wing_mgr
    app.state.skills_bridge = skills_bridge
    app.state.nudge_cache = nudge_cache
    app.state.conv_buffer = conv_buffer
    app.state.rule_detector = rule_detector
    app.state.nudge_injector = nudge_injector
    app.state.batch_analyzer = batch_analyzer
    try:
        yield
    finally:
        bg_scheduler.shutdown(wait=False)
        live.stop()
