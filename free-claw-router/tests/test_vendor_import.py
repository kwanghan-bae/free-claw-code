def test_vendored_types_import():
    from router.vendor.openspace_engine.types import SkillRecord, EvolutionSuggestion, EvolutionType
    assert SkillRecord is not None
    assert EvolutionType.FIX is not None

def test_vendored_store_import():
    from router.vendor.openspace_engine.store import SkillStore
    assert SkillStore is not None

def test_vendored_analyzer_import():
    from router.vendor.openspace_engine.analyzer import ExecutionAnalyzer
    assert ExecutionAnalyzer is not None

def test_vendored_evolver_import():
    from router.vendor.openspace_engine.evolver import SkillEvolver
    assert SkillEvolver is not None

def test_shim_logger():
    from router.vendor.openspace_engine.shims.logger import Logger
    log = Logger("test")
    log.info("smoke test")

def test_shim_llm_client():
    from router.vendor.openspace_engine.shims.llm_client import LLMClient
    c = LLMClient()
    assert c is not None
