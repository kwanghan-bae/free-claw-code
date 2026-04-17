from router.meta.meta_evaluator import MetaEvaluator, Verdict

def test_improved_when_metrics_better():
    pre = {"success_rate": 0.70, "tool_success_rate": 0.65, "mistake_count": 5}
    post = {"success_rate": 0.85, "tool_success_rate": 0.80, "mistake_count": 2}
    ev = MetaEvaluator(degradation_threshold=0.15)
    assert ev.evaluate(pre, post) == Verdict.KEEP

def test_degraded_when_metrics_worse():
    pre = {"success_rate": 0.85, "tool_success_rate": 0.80, "mistake_count": 2}
    post = {"success_rate": 0.60, "tool_success_rate": 0.55, "mistake_count": 6}
    ev = MetaEvaluator(degradation_threshold=0.15)
    assert ev.evaluate(pre, post) == Verdict.REVERT

def test_inconclusive_when_mixed():
    pre = {"success_rate": 0.70, "tool_success_rate": 0.80, "mistake_count": 5}
    post = {"success_rate": 0.85, "tool_success_rate": 0.60, "mistake_count": 5}
    ev = MetaEvaluator(degradation_threshold=0.15)
    assert ev.evaluate(pre, post) == Verdict.INCONCLUSIVE

def test_keep_when_stable():
    pre = {"success_rate": 0.80, "tool_success_rate": 0.75, "mistake_count": 3}
    post = {"success_rate": 0.79, "tool_success_rate": 0.74, "mistake_count": 3}
    ev = MetaEvaluator(degradation_threshold=0.15)
    assert ev.evaluate(pre, post) == Verdict.KEEP
