# Catalog-refresh PR review instructions

You are reviewing an automated PR that updates
`free-claw-router/router/catalog/data/<provider>.yaml`.

## Must-check list

1. **Free-only invariant** — every modified model has `pricing: {input: 0, output: 0, free: true}`.
2. **Evidence** — each entry has at least one `evidence_urls` entry matching `ops/allowed_sources.yaml`.
3. **Freshness** — `last_verified` is within 48 hours of the PR timestamp.
4. **Quirk plausibility** — `quirks` entries are specific and actionable.
5. **Context window sanity** — `context_window` > 0 and plausible for the model.
6. **Deprecation hygiene** — if `status == deprecated`, both `deprecation_reason` and `replaced_by` must exist.
7. **No secrets** — no API keys, tokens, or credentials in YAML or PR body.

## Output format

Post a single PR review via `gh pr review --comment` with:
- Header: `Catalog review: APPROVE | REQUEST_CHANGES | NEEDS_INVESTIGATION`
- Bullet list of findings.
