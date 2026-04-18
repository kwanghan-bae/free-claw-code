from contextlib import asynccontextmanager
import json
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
from router.learning.insight_generator import InsightGenerator
from router.learning.trajectory_compressor import TrajectoryCompressor
from router.dispatch.client import DispatchClient
from router.meta.meta_analyzer import MetaAnalyzer
from router.meta.meta_suggestions import SuggestionStore
from router.meta.meta_consensus import build_edit_plans
from router.meta.meta_editor import MetaEditor
from router.meta.meta_pr import MetaPR

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

    # Insight + trajectory hooks (P3, fire on session-close mining)
    import os

    def _search_mempalace(query, wing=None, n_results=5):
        from mempalace.searcher import search_memories
        return search_memories(query, palace_path=os.path.expanduser("~/.mempalace/palace"),
                               wing=wing, n_results=n_results)

    def _add_mempalace_drawer(wing, room, content):
        from mempalace.mcp_server import tool_add_drawer
        tool_add_drawer(wing=wing, room=room, content=content)

    insight_gen = InsightGenerator(
        search_fn=_search_mempalace, llm_fn=_batch_llm, add_drawer_fn=_add_mempalace_drawer,
    )
    traj_comp = TrajectoryCompressor(llm_fn=_batch_llm, add_drawer_fn=_add_mempalace_drawer)

    def _insight_hook(trace_id, transcript, wing):
        import asyncio
        try:
            asyncio.run(insight_gen.generate(project_wing=wing))
        except RuntimeError:
            # Event loop already running — use create_task instead
            loop = asyncio.get_event_loop()
            loop.create_task(insight_gen.generate(project_wing=wing))

    def _trajectory_hook(trace_id, transcript, wing):
        import asyncio
        try:
            asyncio.run(traj_comp.compress(trace_id=trace_id, transcript=transcript, project_wing=wing))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            loop.create_task(traj_comp.compress(trace_id=trace_id, transcript=transcript, project_wing=wing))

    session_detector._on_mine_hooks.append(_insight_hook)
    session_detector._on_mine_hooks.append(_trajectory_hook)

    # Meta-evolution (P4)
    suggestions_path = Path.home() / ".free-claw-router" / "meta_suggestions.json"
    meta_store = SuggestionStore(path=suggestions_path)
    targets_path = Path(__file__).resolve().parent.parent / "meta" / "meta_targets.yaml"
    meta_analyzer = MetaAnalyzer(llm_fn=_batch_llm, targets_path=targets_path)

    def _meta_hook(trace_id, transcript, wing):
        """Extract trajectory from mempalace and analyze for meta-suggestions."""
        import asyncio
        try:
            # Read the latest trajectory from mempalace (just stored by P3)
            from mempalace.searcher import search_memories
            import os
            results = search_memories(
                f"trajectory session {trace_id[:8]}",
                palace_path=os.path.expanduser("~/.mempalace/palace"),
                wing=wing, room="trajectories", n_results=1,
            )
            trajectory = {}
            for r in results.get("results", []):
                try:
                    trajectory = json.loads(r.get("content", "{}"))
                    break
                except json.JSONDecodeError:
                    pass
            if trajectory:
                suggestions = asyncio.run(meta_analyzer.analyze(trace_id=trace_id, trajectory=trajectory))
                for s in suggestions:
                    meta_store.append(s)
        except RuntimeError:
            pass  # event loop issue -- best effort
        except Exception:
            import logging
            logging.getLogger(__name__).warning("Meta hook failed", exc_info=True)

    session_detector._on_mine_hooks.append(_meta_hook)

    # Daily meta-evolution cron
    def _daily_meta_evolution():
        import logging
        log = logging.getLogger("meta_cron")
        meta_store.prune()
        all_suggestions = meta_store.read_all()
        plans = build_edit_plans(all_suggestions)
        if not plans:
            log.info("No meta edit plans reached consensus")
            return
        editor = MetaEditor(base_dir=Path(__file__).resolve().parent.parent)
        for plan in plans:
            if editor.apply(plan):
                log.info("Applied meta edit: %s", plan.direction)
                meta_store.clear_target(plan.target_file)
            else:
                log.warning("Meta edit failed: %s", plan.direction)

    from apscheduler.schedulers.background import BackgroundScheduler
    bg_scheduler = BackgroundScheduler()
    bg_scheduler.add_job(session_detector.check_and_mine, "interval", seconds=60, id="session_close_check")

    # Register periodic trigger jobs
    register_trigger_jobs(bg_scheduler, telemetry_store=store, skill_bridge=skills_bridge)

    bg_scheduler.add_job(_daily_meta_evolution, "cron", hour=3, id="daily_meta_evolution")

    # Daily store GC (P5 B-3) — two-phase safety, FCR_GC_PAUSED=1 to disable.
    def _gc_job():
        import logging
        from router.server.gc import run_gc, GcConfig
        gc_log = logging.getLogger("meta_gc")
        data_dir = Path.home() / ".free-claw-router"
        try:
            stats = run_gc(
                data_dir / "telemetry.db",
                data_dir / "meta_suggestions.json",
                GcConfig(),
            )
            gc_log.info("gc_run %s", stats)
        except Exception:
            gc_log.exception("gc_run failed")

    bg_scheduler.add_job(_gc_job, "cron", hour=3, minute=15, id="daily_gc", replace_existing=True)

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
