from router.quota.predict import estimate_request_tokens, Affordability, assess

def test_estimate_is_prompt_plus_max_tokens():
    payload = {"messages": [{"role": "user", "content": "a" * 400}], "max_tokens": 512}
    est = estimate_request_tokens(payload)
    assert 100 <= est <= 700

def test_assess_returns_sufficient_when_plenty_left():
    result = assess(estimated=100, rpm_remaining=20, tpm_remaining=10000)
    assert result is Affordability.SUFFICIENT

def test_assess_returns_tight_when_close_to_limit():
    result = assess(estimated=100, rpm_remaining=1, tpm_remaining=10000)
    assert result is Affordability.TIGHT

def test_assess_returns_insufficient_when_over():
    result = assess(estimated=500, rpm_remaining=1, tpm_remaining=100)
    assert result is Affordability.INSUFFICIENT
