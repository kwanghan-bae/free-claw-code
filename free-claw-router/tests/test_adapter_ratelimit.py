from router.adapters.hermes_ratelimit import parse_rate_limit_headers

SAMPLE = {
    "x-ratelimit-limit-requests": "60",
    "x-ratelimit-limit-tokens": "150000",
    "x-ratelimit-remaining-requests": "55",
    "x-ratelimit-remaining-tokens": "148000",
    "x-ratelimit-reset-requests": "12",
    "x-ratelimit-reset-tokens": "45",
}

def test_parses_minute_buckets():
    state = parse_rate_limit_headers(SAMPLE)
    assert state.requests_min.limit == 60
    assert state.requests_min.remaining == 55
    assert state.requests_min.reset_seconds == 12.0
    assert state.tokens_min.limit == 150000
    assert state.tokens_min.remaining == 148000

def test_missing_headers_yields_zero_buckets():
    state = parse_rate_limit_headers({})
    assert state.requests_min.limit == 0
    assert state.tokens_min.limit == 0

def test_usage_percent_computed():
    state = parse_rate_limit_headers(SAMPLE)
    assert 7 <= state.requests_min.usage_pct <= 10
