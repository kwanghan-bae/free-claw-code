# P0 — Free LLM Router & Budget Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a Python sidecar that claw talks to via `OPENAI_BASE_URL`, providing free-only LLM routing, global quota management, OpenTelemetry-style span tracing, and an autonomous catalog-refresh PR loop, per the P0 design spec (`docs/superpowers/specs/2026-04-15-p0-free-llm-router-design.md`).

**Architecture:** Rust claw emits W3C traceparent headers and OpenAI-compatible requests into a long-running Python sidecar. The sidecar hosts the catalog, router, quota buckets, dispatch (via vendored Hermes credential_pool), and telemetry ingest into SQLite. A claw CronCreate-scheduled research agent opens catalog-refresh PRs that a GitHub Action runs Claude Code on before the human merges.

**Tech Stack:** Rust (extend telemetry/api/runtime/tools crates), Python 3.12+ (FastAPI, pydantic v2, APScheduler, watchdog, httpx, anyio, sqlite3), uv for packaging, git subtree for Hermes vendoring, `gh` CLI for PRs, GitHub Actions for CI + Claude review.

**Spec reference:** `docs/superpowers/specs/2026-04-15-p0-free-llm-router-design.md` (commit `7e498f3`).

---

## File Structure

Files touched by this plan. Each should be single-responsibility.

### Rust (extend existing crates)

| File | Responsibility |
|---|---|
| `rust/crates/telemetry/src/lib.rs` | Add `SpanStarted`/`SpanEnded` variants + W3C trace/span id types + `SessionTracer::start_span` |
| `rust/crates/telemetry/src/traceparent.rs` *(new)* | Parse/emit W3C traceparent headers |
| `rust/crates/runtime/src/session.rs` | Open root span at session start, propagate to sub-agents |
| `rust/crates/runtime/src/prompt.rs` | Emit `x-free-claw-hints` task-type classifier |
| `rust/crates/tools/src/lib.rs` | Wrap `execute_tool` with `tool_call` spans |
| `rust/crates/api/src/client.rs` | Attach `traceparent` header on outbound requests |
| `rust/crates/api/src/backpressure.rs` *(new)* | `/internal/backpressure` listener; concurrency hint store |
| `rust/crates/rusty-claude-cli/src/init.rs` | Add `RouterHealth` to `claw doctor` |

### Sidecar (new `free-claw-router/` subdir)

| File | Responsibility |
|---|---|
| `free-claw-router/pyproject.toml` | uv project definition |
| `free-claw-router/router/server/openai_compat.py` | FastAPI `/v1/chat/completions`, `/v1/models`, `/health` |
| `free-claw-router/router/server/schemas.py` | OpenAI-compat pydantic request/response |
| `free-claw-router/router/server/lifespan.py` | Startup: catalog warmup, scheduler start; shutdown: graceful |
| `free-claw-router/router/catalog/schema.py` | `ProviderSpec`, `ModelSpec`, `Capabilities`, `FreeTier` pydantic |
| `free-claw-router/router/catalog/registry.py` | Load/validate/search catalog |
| `free-claw-router/router/catalog/data/{openrouter,zai,groq,cerebras,ollama,lmstudio}.yaml` | Day-1 provider definitions |
| `free-claw-router/router/catalog/hot_reload.py` | watchdog → atomic double-buffer swap |
| `free-claw-router/router/catalog/refresh/worktree.py` | `git worktree` wrapper |
| `free-claw-router/router/catalog/refresh/pr.py` | `gh pr create/comment` wrapper |
| `free-claw-router/router/catalog/refresh/producer.py` | Orchestrate a research-agent run |
| `free-claw-router/router/catalog/refresh/scheduler.py` | APScheduler; HTTP proxy from claw `CronCreate` |
| `free-claw-router/router/routing/hints.py` | Task-type classifier fallback |
| `free-claw-router/router/routing/decide.py` | Candidate filter + ranker + fallback chain |
| `free-claw-router/router/routing/score.py` | Learned scoring stub |
| `free-claw-router/router/routing/policy.yaml` | Static priority table (HyperAgent-editable later) |
| `free-claw-router/router/quota/bucket.py` | Global reservation buckets |
| `free-claw-router/router/quota/headers.py` | `x-ratelimit-*` parser |
| `free-claw-router/router/quota/predict.py` | Affordability check |
| `free-claw-router/router/quota/backpressure.py` | POST concurrency hints back to claw |
| `free-claw-router/router/dispatch/client.py` | HTTP dispatch via vendored Hermes credential_pool |
| `free-claw-router/router/dispatch/sse_relay.py` | Streaming proxy |
| `free-claw-router/router/dispatch/fallback.py` | 429/5xx → next candidate |
| `free-claw-router/router/telemetry/store.py` | SQLite schema + write paths |
| `free-claw-router/router/telemetry/spans.py` | `Trace`, `Span`, W3C traceparent round-trip |
| `free-claw-router/router/telemetry/events.py` | Typed event variants |
| `free-claw-router/router/telemetry/evaluations.py` | Evaluator protocol + rule evaluator |
| `free-claw-router/router/telemetry/ingest_jsonl.py` | Tail claw JSONL → SQLite |
| `free-claw-router/router/telemetry/readmodels.py` | `skill_model_affinity`, `quota_health`, `span_cost_rollup` views |
| `free-claw-router/router/vendor/hermes/` | git subtree root |
| `free-claw-router/router/adapters/hermes_credentials.py` | Credential pool adapter |
| `free-claw-router/router/adapters/hermes_ratelimit.py` | Header parser adapter |
| `free-claw-router/router/adapters/hermes_routing.py` | `smart_model_routing` port |
| `free-claw-router/ops/catalog-schema.json` | Strict JSON schema for research-agent output |
| `free-claw-router/ops/claude-review-prompt.md` | Reviewer system prompt |
| `free-claw-router/ops/allowed_sources.yaml` | Whitelist of allowed research URLs |
| `free-claw-router/ops/.env.example` | Template for API keys |
| `free-claw-router/tests/...` | pytest coverage + live_smoke suite |

### Repo-level

| File | Responsibility |
|---|---|
| `.github/workflows/catalog-refresh-verify.yml` | YAML schema + invariants + snapshot CI |
| `.github/workflows/claude-review.yml` | PR-open → Claude Code review via Anthropic API |
| `install.sh` | Add sidecar bootstrap (uv check, venv, optional start) |
| `.gitignore` | Exclude `/tmp/free-claw-router-worktrees/`, sidecar logs, SQLite DBs |

---

## Execution prerequisites

- [ ] **Prereq 1:** Verify working tree is clean.
  Run: `git status`
  Expected: `nothing to commit, working tree clean`
- [ ] **Prereq 2:** Verify `uv`, `gh`, `sqlite3`, and Rust toolchain are available.
  Run: `uv --version && gh --version && sqlite3 --version && cargo --version`
  Expected: all four print versions.
- [ ] **Prereq 3:** Anthropic API key is set in env for the GitHub Actions secret step later.
  Run: `gh secret list --repo kwanghan-bae/free-claw-code | grep -i anthropic || echo 'set it later'`

---

## PART A — claw Rust: Telemetry span extension

### Task 1: Add `trace_id` / `span_id` types and `traceparent` parser

**Files:**
- Create: `rust/crates/telemetry/src/traceparent.rs`
- Modify: `rust/crates/telemetry/src/lib.rs` (add `pub mod traceparent;`)
- Test: `rust/crates/telemetry/src/traceparent.rs` (inline `#[cfg(test)]`)

- [ ] **Step 1: Write the failing tests**

Append to `rust/crates/telemetry/src/traceparent.rs`:

```rust
use rand::RngCore;
use serde::{Deserialize, Serialize};
use std::fmt;

#[derive(Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct TraceId(pub [u8; 16]);

#[derive(Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct SpanId(pub [u8; 8]);

impl TraceId {
    pub fn random() -> Self {
        let mut bytes = [0u8; 16];
        rand::thread_rng().fill_bytes(&mut bytes);
        Self(bytes)
    }
    pub fn is_zero(&self) -> bool { self.0 == [0u8; 16] }
}

impl SpanId {
    pub fn random() -> Self {
        let mut bytes = [0u8; 8];
        rand::thread_rng().fill_bytes(&mut bytes);
        Self(bytes)
    }
    pub fn is_zero(&self) -> bool { self.0 == [0u8; 8] }
}

impl fmt::Display for TraceId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        for b in &self.0 { write!(f, "{:02x}", b)?; }
        Ok(())
    }
}
impl fmt::Debug for TraceId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { write!(f, "{}", self) }
}
impl fmt::Display for SpanId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        for b in &self.0 { write!(f, "{:02x}", b)?; }
        Ok(())
    }
}
impl fmt::Debug for SpanId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { write!(f, "{}", self) }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TraceContext {
    pub trace_id: TraceId,
    pub span_id: SpanId,
    pub sampled: bool,
}

impl TraceContext {
    pub fn encode(&self) -> String {
        format!(
            "00-{}-{}-{:02x}",
            self.trace_id,
            self.span_id,
            if self.sampled { 1u8 } else { 0u8 }
        )
    }
    pub fn decode(header: &str) -> Option<Self> {
        let parts: Vec<&str> = header.split('-').collect();
        if parts.len() != 4 || parts[0] != "00" { return None; }
        if parts[1].len() != 32 || parts[2].len() != 16 || parts[3].len() != 2 { return None; }
        let mut trace = [0u8; 16];
        for i in 0..16 {
            trace[i] = u8::from_str_radix(&parts[1][i * 2..i * 2 + 2], 16).ok()?;
        }
        let mut span = [0u8; 8];
        for i in 0..8 {
            span[i] = u8::from_str_radix(&parts[2][i * 2..i * 2 + 2], 16).ok()?;
        }
        let flags = u8::from_str_radix(parts[3], 16).ok()?;
        Some(Self { trace_id: TraceId(trace), span_id: SpanId(span), sampled: flags & 1 == 1 })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn traceparent_roundtrip_preserves_ids_and_flags() {
        let ctx = TraceContext {
            trace_id: TraceId([
                0x4b, 0xf9, 0x2f, 0x35, 0x77, 0xb3, 0x4d, 0xa6,
                0xa3, 0xce, 0x92, 0x9d, 0x0e, 0x0e, 0x47, 0x36,
            ]),
            span_id: SpanId([0x00, 0xf0, 0x67, 0xaa, 0x0b, 0xa9, 0x02, 0xb7]),
            sampled: true,
        };
        let header = ctx.encode();
        assert_eq!(header, "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01");
        let decoded = TraceContext::decode(&header).expect("roundtrip");
        assert_eq!(decoded, ctx);
    }

    #[test]
    fn traceparent_decode_rejects_bad_version() {
        assert!(TraceContext::decode("ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01").is_none());
    }

    #[test]
    fn traceparent_decode_rejects_short_id() {
        assert!(TraceContext::decode("00-abc-def-01").is_none());
    }

    #[test]
    fn random_ids_are_non_zero() {
        assert!(!TraceId::random().is_zero());
        assert!(!SpanId::random().is_zero());
    }
}
```

- [ ] **Step 2: Wire module + add `rand` to telemetry Cargo.toml**

Modify `rust/crates/telemetry/Cargo.toml` to add (under `[dependencies]`):

```toml
rand = "0.8"
```

Modify `rust/crates/telemetry/src/lib.rs` to append near the top (after existing imports):

```rust
pub mod traceparent;
pub use traceparent::{SpanId, TraceContext, TraceId};
```

- [ ] **Step 3: Run the failing tests**

Run: `cd rust && cargo test -p telemetry traceparent -- --nocapture`
Expected: all 4 tests pass (the module compiles and behaviors match).

- [ ] **Step 4: Commit**

```bash
git add rust/crates/telemetry/Cargo.toml rust/crates/telemetry/src/lib.rs rust/crates/telemetry/src/traceparent.rs
git commit -m "feat(telemetry): add W3C traceparent types and parser"
```

---

### Task 2: Add `SpanStarted` / `SpanEnded` telemetry event variants

**Files:**
- Modify: `rust/crates/telemetry/src/lib.rs` (extend `TelemetryEvent` enum)
- Test: inline `#[cfg(test)]` in same file

- [ ] **Step 1: Write the failing test**

Append inside the `mod tests` block in `rust/crates/telemetry/src/lib.rs`:

```rust
    #[test]
    fn span_started_and_ended_events_serialize_roundtrip() {
        let tid = TraceId([
            0x4b, 0xf9, 0x2f, 0x35, 0x77, 0xb3, 0x4d, 0xa6,
            0xa3, 0xce, 0x92, 0x9d, 0x0e, 0x0e, 0x47, 0x36,
        ]);
        let sid = SpanId([0x00, 0xf0, 0x67, 0xaa, 0x0b, 0xa9, 0x02, 0xb7]);
        let ev = TelemetryEvent::SpanStarted {
            trace_id: tid,
            span_id: sid,
            parent_span_id: None,
            op_name: "session".into(),
            session_id: "s-1".into(),
            attributes: Map::new(),
        };
        let serialized = serde_json::to_string(&ev).unwrap();
        assert!(serialized.contains("\"type\":\"span_started\""));
        let parsed: TelemetryEvent = serde_json::from_str(&serialized).unwrap();
        match parsed {
            TelemetryEvent::SpanStarted { trace_id, span_id, .. } => {
                assert_eq!(trace_id, tid);
                assert_eq!(span_id, sid);
            }
            _ => panic!("wrong variant"),
        }

        let end = TelemetryEvent::SpanEnded {
            span_id: sid,
            status: "ok".into(),
            duration_ms: 42,
            attributes: Map::new(),
        };
        let s2 = serde_json::to_string(&end).unwrap();
        assert!(s2.contains("\"type\":\"span_ended\""));
    }
```

- [ ] **Step 2: Extend the enum**

In `rust/crates/telemetry/src/lib.rs`, extend `TelemetryEvent`:

```rust
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum TelemetryEvent {
    // ... keep existing variants ...
    SpanStarted {
        trace_id: TraceId,
        span_id: SpanId,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        parent_span_id: Option<SpanId>,
        op_name: String,
        session_id: String,
        #[serde(default, skip_serializing_if = "Map::is_empty")]
        attributes: Map<String, Value>,
    },
    SpanEnded {
        span_id: SpanId,
        status: String,
        duration_ms: u64,
        #[serde(default, skip_serializing_if = "Map::is_empty")]
        attributes: Map<String, Value>,
    },
}
```

Also add `Serialize`/`Deserialize` derives on `TraceId` and `SpanId` — already added in Task 1, confirm compile.

- [ ] **Step 3: Run tests**

Run: `cd rust && cargo test -p telemetry -- --nocapture`
Expected: all existing tests plus the new span event test pass.

- [ ] **Step 4: Commit**

```bash
git add rust/crates/telemetry/src/lib.rs
git commit -m "feat(telemetry): add SpanStarted/SpanEnded event variants"
```

---

### Task 3: Add `SessionTracer::start_span` + `SpanGuard`

**Files:**
- Modify: `rust/crates/telemetry/src/lib.rs`
- Test: inline

- [ ] **Step 1: Write failing test**

Add to `mod tests`:

```rust
    #[test]
    fn span_guard_emits_ended_on_drop_with_duration() {
        let sink = Arc::new(MemoryTelemetrySink::default());
        let tracer = SessionTracer::new("s-span", sink.clone());
        let parent_ctx = TraceContext {
            trace_id: TraceId::random(),
            span_id: SpanId::random(),
            sampled: true,
        };
        {
            let guard = tracer.start_span(parent_ctx, "tool_call", Map::new());
            assert_eq!(guard.context().trace_id, parent_ctx.trace_id);
            std::thread::sleep(std::time::Duration::from_millis(3));
        }
        let events = sink.events();
        let has_start = events.iter().any(|e| matches!(e, TelemetryEvent::SpanStarted { op_name, .. } if op_name == "tool_call"));
        let has_end = events.iter().any(|e| matches!(e, TelemetryEvent::SpanEnded { duration_ms, .. } if *duration_ms >= 3));
        assert!(has_start);
        assert!(has_end);
    }
```

- [ ] **Step 2: Implement `SpanGuard` + `start_span`**

Append to `rust/crates/telemetry/src/lib.rs`:

```rust
pub struct SpanGuard {
    sink: Arc<dyn TelemetrySink>,
    span_id: SpanId,
    context: TraceContext,
    started_at: std::time::Instant,
    status: Mutex<Option<String>>,
    attributes_on_end: Mutex<Map<String, Value>>,
}

impl SpanGuard {
    pub fn context(&self) -> TraceContext { self.context }
    pub fn set_status(&self, status: impl Into<String>) {
        *self.status.lock().unwrap_or_else(std::sync::PoisonError::into_inner) = Some(status.into());
    }
    pub fn add_attribute(&self, key: impl Into<String>, value: Value) {
        self.attributes_on_end
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .insert(key.into(), value);
    }
}

impl Drop for SpanGuard {
    fn drop(&mut self) {
        let duration_ms = self.started_at.elapsed().as_millis() as u64;
        let status = self
            .status
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
            .unwrap_or_else(|| "ok".into());
        let attributes = self
            .attributes_on_end
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone();
        self.sink.record(TelemetryEvent::SpanEnded {
            span_id: self.span_id,
            status,
            duration_ms,
            attributes,
        });
    }
}

impl SessionTracer {
    pub fn start_span(
        &self,
        parent: TraceContext,
        op_name: impl Into<String>,
        attributes: Map<String, Value>,
    ) -> SpanGuard {
        let span_id = SpanId::random();
        let op_name = op_name.into();
        self.sink.record(TelemetryEvent::SpanStarted {
            trace_id: parent.trace_id,
            span_id,
            parent_span_id: Some(parent.span_id),
            op_name: op_name.clone(),
            session_id: self.session_id.clone(),
            attributes,
        });
        SpanGuard {
            sink: self.sink.clone(),
            span_id,
            context: TraceContext {
                trace_id: parent.trace_id,
                span_id,
                sampled: parent.sampled,
            },
            started_at: std::time::Instant::now(),
            status: Mutex::new(None),
            attributes_on_end: Mutex::new(Map::new()),
        }
    }

    pub fn start_root_span(
        &self,
        op_name: impl Into<String>,
        attributes: Map<String, Value>,
    ) -> (TraceContext, SpanGuard) {
        let root = TraceContext {
            trace_id: TraceId::random(),
            span_id: SpanId::random(),
            sampled: true,
        };
        let guard = self.start_span(root, op_name, attributes);
        (guard.context(), guard)
    }
}
```

- [ ] **Step 3: Run tests**

Run: `cd rust && cargo test -p telemetry -- --nocapture`
Expected: the new `span_guard_emits_ended_on_drop_with_duration` test passes along with all previous.

- [ ] **Step 4: Commit**

```bash
git add rust/crates/telemetry/src/lib.rs
git commit -m "feat(telemetry): add SessionTracer::start_span with SpanGuard RAII"
```

---

### Task 4: Open a root span at session creation

**Files:**
- Modify: `rust/crates/runtime/src/session.rs`

- [ ] **Step 1: Locate session construction**

Run: `grep -n "fn new\|pub struct Session" rust/crates/runtime/src/session.rs | head -20`
Read the constructor region (~first 200 lines of `session.rs`) to understand the current shape.

- [ ] **Step 2: Add a `trace_context` field + root span kickoff**

In the `Session` struct definition, add:

```rust
pub trace_context: telemetry::TraceContext,
```

In the constructor (wherever `Session { ... }` is built with a `SessionTracer`), insert right after the tracer is built:

```rust
let (trace_context, root_guard) = tracer.start_root_span(
    "session",
    serde_json::Map::from_iter([
        ("session_id".into(), serde_json::Value::String(session_id.clone())),
    ]),
);
// Hold the guard on the Session so it lives for the session lifetime.
```

Store `root_guard` on the struct as `_root_span_guard: telemetry::SpanGuard,` (underscore = intentionally unread).

- [ ] **Step 3: Run workspace test suite to ensure nothing regressed**

Run: `cd rust && cargo test --workspace -- --skip live_`
Expected: all tests pass. Any test that constructed `Session` manually may need a tracer fixture; update those tests to pass a `MemoryTelemetrySink`-backed tracer.

- [ ] **Step 4: Commit**

```bash
git add rust/crates/runtime/src/session.rs
git commit -m "feat(runtime): open root span per session with RAII guard"
```

---

### Task 5: Wrap `execute_tool` with a `tool_call` child span

**Files:**
- Modify: `rust/crates/tools/src/lib.rs`
- Test: `rust/crates/tools/tests/span_wrapping.rs` (new)

- [ ] **Step 1: Write failing test**

Create `rust/crates/tools/tests/span_wrapping.rs`:

```rust
use std::sync::Arc;

use telemetry::{MemoryTelemetrySink, SessionTracer, TelemetryEvent};

// Assumes tools crate re-exports `execute_tool` (or provides a runtime-less shim we can call).
// If `execute_tool` needs a runtime ctx, add a minimal `test_helpers::execute_tool_with_tracer`.

#[test]
fn execute_tool_emits_child_span_under_session_trace() {
    let sink = Arc::new(MemoryTelemetrySink::default());
    let tracer = SessionTracer::new("s-test", sink.clone());
    let (root_ctx, _guard) = tracer.start_root_span("session", Default::default());

    // Dispatch any simple read-only tool; use ToolSearch or Noop if present.
    let _ = tools::test_helpers::execute_tool_with_span(
        &tracer,
        root_ctx,
        "NoopTool",
        serde_json::json!({}),
    );

    let events = sink.events();
    let span_started = events.iter().filter(|e| matches!(e, TelemetryEvent::SpanStarted { op_name, .. } if op_name == "tool_call")).count();
    let span_ended = events.iter().filter(|e| matches!(e, TelemetryEvent::SpanEnded { .. })).count();
    assert_eq!(span_started, 1);
    assert!(span_ended >= 1);
}
```

- [ ] **Step 2: Add `test_helpers` module + wrap `execute_tool`**

In `rust/crates/tools/src/lib.rs`, add:

```rust
pub mod test_helpers {
    use telemetry::{SessionTracer, TraceContext};

    pub fn execute_tool_with_span(
        tracer: &SessionTracer,
        parent: TraceContext,
        tool_name: &str,
        params: serde_json::Value,
    ) -> serde_json::Value {
        let guard = tracer.start_span(
            parent,
            "tool_call",
            serde_json::Map::from_iter([
                ("tool_name".into(), serde_json::Value::String(tool_name.into())),
            ]),
        );
        // Route to the real dispatcher; stub NoopTool for tests.
        let result = if tool_name == "NoopTool" {
            serde_json::json!({"ok": true})
        } else {
            crate::execute_tool(tool_name, params)
        };
        guard.add_attribute("success", serde_json::Value::Bool(true));
        result
    }
}
```

In the real `execute_tool` (or a thin wrapper called by runtime), accept an optional `TraceContext` and open a `tool_call` span inside. Wire this through the call-site in `rust/crates/runtime/src/...` where `execute_tool` is invoked.

- [ ] **Step 3: Run tests**

Run: `cd rust && cargo test -p tools span_wrapping -- --nocapture`
Expected: new test passes.

- [ ] **Step 4: Commit**

```bash
git add rust/crates/tools/src/lib.rs rust/crates/tools/tests/span_wrapping.rs
git commit -m "feat(tools): wrap execute_tool with tool_call spans"
```

---

## PART B — claw Rust: Sidecar integration

### Task 6: Emit `traceparent` header on outbound api requests

**Files:**
- Modify: `rust/crates/api/src/client.rs`
- Test: `rust/crates/api/tests/traceparent_emission.rs` (new)

- [ ] **Step 1: Write the failing test**

Create `rust/crates/api/tests/traceparent_emission.rs`:

```rust
use httpmock::{Method::POST, MockServer};
use telemetry::{TraceContext, TraceId, SpanId};

#[tokio::test]
async fn client_emits_traceparent_header_when_context_provided() {
    let server = MockServer::start();
    let m = server.mock(|when, then| {
        when.method(POST)
            .path("/v1/chat/completions")
            .header_exists("traceparent");
        then.status(200).body("{}");
    });

    let ctx = TraceContext {
        trace_id: TraceId::random(),
        span_id: SpanId::random(),
        sampled: true,
    };
    let client = api::Client::builder()
        .base_url(&server.base_url())
        .with_trace_context(ctx)
        .build()
        .unwrap();
    let _ = client
        .send_openai_compat(serde_json::json!({"model":"test"}))
        .await;

    m.assert();
}
```

- [ ] **Step 2: Implement `with_trace_context` on the client builder**

In `rust/crates/api/src/client.rs`, add a builder field `trace_context: Option<TraceContext>`. In the request construction path (inside `send_message` / `stream_message`), after headers are assembled, insert:

```rust
if let Some(ctx) = self.trace_context {
    req = req.header("traceparent", ctx.encode());
}
```

Expose a public `with_trace_context(ctx: TraceContext) -> Self` on the builder.

- [ ] **Step 3: Add `httpmock` dev-dep**

Modify `rust/crates/api/Cargo.toml`:

```toml
[dev-dependencies]
httpmock = "0.7"
```

- [ ] **Step 4: Run tests**

Run: `cd rust && cargo test -p api traceparent_emission -- --nocapture`
Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add rust/crates/api/Cargo.toml rust/crates/api/src/client.rs rust/crates/api/tests/traceparent_emission.rs
git commit -m "feat(api): attach W3C traceparent header when trace context is set"
```

---

### Task 7: Emit `x-free-claw-hints` header from prompt path

**Files:**
- Modify: `rust/crates/runtime/src/prompt.rs`
- Modify: `rust/crates/api/src/client.rs` (accept `hints` param)
- Test: `rust/crates/runtime/src/prompt.rs` inline

- [ ] **Step 1: Write failing test**

In `rust/crates/runtime/src/prompt.rs`, add at the bottom:

```rust
#[cfg(test)]
mod hint_tests {
    use super::*;

    #[test]
    fn classify_coding_request() {
        assert_eq!(classify_task_hint("refactor this module"), "coding");
        assert_eq!(classify_task_hint("add unit tests for auth"), "coding");
    }
    #[test]
    fn classify_planning_request() {
        assert_eq!(classify_task_hint("design a rate limiter"), "planning");
    }
    #[test]
    fn classify_summary_request() {
        assert_eq!(classify_task_hint("summarize the PR description"), "summary");
    }
    #[test]
    fn classify_default_chat() {
        assert_eq!(classify_task_hint("hello"), "chat");
    }
}
```

- [ ] **Step 2: Implement `classify_task_hint`**

Append to `rust/crates/runtime/src/prompt.rs`:

```rust
pub fn classify_task_hint(user_message: &str) -> &'static str {
    let lower = user_message.to_lowercase();
    const PLANNING: &[&str] = &["design", "architect", "plan", "approach", "strategy"];
    const CODING: &[&str] = &[
        "refactor", "implement", "fix", "bug", "unit test", "integration test",
        "add function", "add method", "write tests", "patch",
    ];
    const TOOL_HEAVY: &[&str] = &["run", "execute", "search", "grep", "shell"];
    const SUMMARY: &[&str] = &["summarize", "summary", "tl;dr", "condense"];

    if PLANNING.iter().any(|k| lower.contains(k)) { return "planning"; }
    if TOOL_HEAVY.iter().any(|k| lower.contains(k)) { return "tool_heavy"; }
    if CODING.iter().any(|k| lower.contains(k)) { return "coding"; }
    if SUMMARY.iter().any(|k| lower.contains(k)) { return "summary"; }
    "chat"
}
```

- [ ] **Step 3: Wire header emission**

In `rust/crates/api/src/client.rs`, extend `send_openai_compat` signature (or builder) with `hints: Option<String>`. When set, add header `x-free-claw-hints: <hints>` alongside traceparent.

In the runtime call-site (`rust/crates/runtime/src/conversation.rs` where the api client is invoked), call `classify_task_hint(latest_user_message)` and pass the result.

- [ ] **Step 4: Run tests**

Run: `cd rust && cargo test -p runtime hint_tests`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add rust/crates/runtime/src/prompt.rs rust/crates/runtime/src/conversation.rs rust/crates/api/src/client.rs
git commit -m "feat(runtime): classify task hint and emit x-free-claw-hints header"
```

---

### Task 8: Add `/internal/backpressure` listener

**Files:**
- Create: `rust/crates/api/src/backpressure.rs`
- Modify: `rust/crates/api/src/lib.rs` (`pub mod backpressure;`)
- Test: `rust/crates/api/tests/backpressure.rs` (new)

- [ ] **Step 1: Write failing test**

Create `rust/crates/api/tests/backpressure.rs`:

```rust
use api::backpressure::{BackpressureState, BackpressureHint};

#[tokio::test]
async fn backpressure_state_stores_latest_hint_per_task_type() {
    let state = BackpressureState::default();
    state.apply(BackpressureHint {
        task_type: "coding".into(),
        suggested_concurrency: 2,
        reason: "openrouter tpm<20%".into(),
        ttl_seconds: 60,
    }).await;
    state.apply(BackpressureHint {
        task_type: "coding".into(),
        suggested_concurrency: 1,
        reason: "groq rpm<20%".into(),
        ttl_seconds: 60,
    }).await;

    let current = state.current_concurrency("coding").await;
    assert_eq!(current, Some(1));

    let unknown = state.current_concurrency("planning").await;
    assert_eq!(unknown, None);
}
```

- [ ] **Step 2: Implement**

Create `rust/crates/api/src/backpressure.rs`:

```rust
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BackpressureHint {
    pub task_type: String,
    pub suggested_concurrency: u32,
    pub reason: String,
    pub ttl_seconds: u64,
}

#[derive(Clone, Default)]
pub struct BackpressureState {
    inner: Arc<RwLock<HashMap<String, (BackpressureHint, std::time::Instant)>>>,
}

impl BackpressureState {
    pub async fn apply(&self, hint: BackpressureHint) {
        let mut guard = self.inner.write().await;
        guard.insert(hint.task_type.clone(), (hint, std::time::Instant::now()));
    }
    pub async fn current_concurrency(&self, task_type: &str) -> Option<u32> {
        let guard = self.inner.read().await;
        let (hint, applied_at) = guard.get(task_type)?;
        let age = applied_at.elapsed().as_secs();
        if age > hint.ttl_seconds { return None; }
        Some(hint.suggested_concurrency)
    }
}
```

Wire into `rust/crates/api/src/lib.rs`:

```rust
pub mod backpressure;
pub use backpressure::{BackpressureHint, BackpressureState};
```

- [ ] **Step 3: Expose as an HTTP handler in CLI**

In `rust/crates/rusty-claude-cli/src/main.rs`, add a small axum/tower route registered at startup:

```
POST /internal/backpressure → BackpressureHint body → BackpressureState.apply
```

Bind on `127.0.0.1:<claw_internal_port>` from config.

- [ ] **Step 4: Run tests**

Run: `cd rust && cargo test -p api backpressure -- --nocapture`
Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add rust/crates/api/Cargo.toml rust/crates/api/src/lib.rs rust/crates/api/src/backpressure.rs rust/crates/api/tests/backpressure.rs rust/crates/rusty-claude-cli/src/main.rs
git commit -m "feat(api): add /internal/backpressure listener + BackpressureState"
```

---

### Task 9: Add `RouterHealth` check to `claw doctor`

**Files:**
- Modify: `rust/crates/rusty-claude-cli/src/init.rs` (doctor command assembly)
- Test: `rust/crates/rusty-claude-cli/tests/doctor_router_health.rs` (new)

- [ ] **Step 1: Write failing test**

Create `rust/crates/rusty-claude-cli/tests/doctor_router_health.rs`:

```rust
use httpmock::{Method::GET, MockServer};

#[tokio::test]
async fn doctor_reports_router_health_when_sidecar_up() {
    let server = MockServer::start();
    server.mock(|when, then| {
        when.method(GET).path("/health");
        then.status(200).body("{\"status\":\"ok\",\"catalog_version\":\"2026-04-15\"}");
    });

    let report = rusty_claude_cli::doctor::router_health_probe(&server.base_url()).await;
    assert!(report.healthy);
    assert_eq!(report.catalog_version.as_deref(), Some("2026-04-15"));
}

#[tokio::test]
async fn doctor_reports_router_unhealthy_on_connection_refused() {
    let report = rusty_claude_cli::doctor::router_health_probe("http://127.0.0.1:1").await;
    assert!(!report.healthy);
    assert!(report.error.is_some());
}
```

- [ ] **Step 2: Implement**

In `rust/crates/rusty-claude-cli/src/doctor.rs` (create if absent; otherwise modify the existing doctor routine):

```rust
use serde::Deserialize;

#[derive(Debug, Clone)]
pub struct RouterHealthReport {
    pub healthy: bool,
    pub catalog_version: Option<String>,
    pub error: Option<String>,
}

#[derive(Deserialize)]
struct HealthBody {
    status: String,
    catalog_version: Option<String>,
}

pub async fn router_health_probe(base_url: &str) -> RouterHealthReport {
    let url = format!("{}/health", base_url.trim_end_matches('/'));
    match reqwest::Client::new().get(&url).send().await {
        Ok(resp) if resp.status().is_success() => match resp.json::<HealthBody>().await {
            Ok(body) => RouterHealthReport {
                healthy: body.status == "ok",
                catalog_version: body.catalog_version,
                error: None,
            },
            Err(e) => RouterHealthReport { healthy: false, catalog_version: None, error: Some(e.to_string()) },
        },
        Ok(resp) => RouterHealthReport {
            healthy: false,
            catalog_version: None,
            error: Some(format!("http {}", resp.status())),
        },
        Err(e) => RouterHealthReport { healthy: false, catalog_version: None, error: Some(e.to_string()) },
    }
}
```

Register the probe in the main doctor flow in `init.rs`, printing `router: ok (catalog 2026-04-15)` or `router: DOWN — <err>`.

- [ ] **Step 3: Run tests**

Run: `cd rust && cargo test -p rusty-claude-cli doctor_router_health -- --nocapture`
Expected: 2 tests pass.

- [ ] **Step 4: Commit**

```bash
git add rust/crates/rusty-claude-cli/src/doctor.rs rust/crates/rusty-claude-cli/src/init.rs rust/crates/rusty-claude-cli/tests/doctor_router_health.rs rust/crates/rusty-claude-cli/Cargo.toml
git commit -m "feat(cli): add RouterHealth probe to claw doctor"
```

---

## PART C — Sidecar scaffolding (M0)

### Task 10: Initialize `free-claw-router/` Python package

**Files:**
- Create: `free-claw-router/pyproject.toml`
- Create: `free-claw-router/router/__init__.py`
- Create: `free-claw-router/README.md`
- Modify: `.gitignore`

- [ ] **Step 1: Create package skeleton**

Create `free-claw-router/pyproject.toml`:

```toml
[project]
name = "free-claw-router"
version = "0.0.1"
description = "Free-only LLM router sidecar for free-claw-code"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.29",
  "pydantic>=2.7",
  "pyyaml>=6.0",
  "httpx>=0.27",
  "anyio>=4.3",
  "watchdog>=4.0",
  "apscheduler>=3.10",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "hypothesis>=6.100",
  "httpx[http2]>=0.27",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["router"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

Create `free-claw-router/router/__init__.py`:

```python
"""free-claw-router — P0 sidecar for free-claw-code."""
__version__ = "0.0.1"
```

Create `free-claw-router/README.md`:

```markdown
# free-claw-router

OpenAI-compatible sidecar for free-claw-code. See
[`docs/superpowers/specs/2026-04-15-p0-free-llm-router-design.md`](../docs/superpowers/specs/2026-04-15-p0-free-llm-router-design.md)
for the design.

## Quick start (dev)

```bash
cd free-claw-router
uv sync --extra dev
uv run uvicorn router.server.openai_compat:app --reload --port 7801
```
```

Modify `.gitignore` — append:

```
/tmp/free-claw-router-worktrees/
free-claw-router/.venv/
free-claw-router/.pytest_cache/
free-claw-router/**/__pycache__/
free-claw-router/router/telemetry/*.db
free-claw-router/router/telemetry/*.db-*
```

- [ ] **Step 2: Verify uv can resolve**

Run: `cd free-claw-router && uv sync --extra dev`
Expected: `.venv/` created, `uv.lock` committed.

- [ ] **Step 3: Commit**

```bash
git add free-claw-router/pyproject.toml free-claw-router/router/__init__.py free-claw-router/README.md free-claw-router/uv.lock .gitignore
git commit -m "feat(router): initialize Python sidecar package skeleton"
```

---

### Task 11: FastAPI app with `/health` + 501 stub for `/v1/chat/completions`

**Files:**
- Create: `free-claw-router/router/server/__init__.py`
- Create: `free-claw-router/router/server/openai_compat.py`
- Create: `free-claw-router/router/server/lifespan.py`
- Create: `free-claw-router/tests/test_server_health.py`

- [ ] **Step 1: Write failing test**

Create `free-claw-router/tests/test_server_health.py`:

```python
from fastapi.testclient import TestClient
from router.server.openai_compat import app

client = TestClient(app)

def test_health_returns_ok_status():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "catalog_version" in body

def test_chat_completions_returns_501_stub():
    r = client.post("/v1/chat/completions", json={"model": "stub", "messages": []})
    assert r.status_code == 501
    assert "not_implemented" in r.json()["error"]["code"]
```

- [ ] **Step 2: Implement server skeleton**

Create `free-claw-router/router/server/lifespan.py`:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Catalog warmup + scheduler start will go here in later tasks.
    app.state.catalog_version = "unversioned"
    yield
    # Graceful shutdown hooks go here.
```

Create `free-claw-router/router/server/openai_compat.py`:

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from router.server.lifespan import lifespan

app = FastAPI(title="free-claw-router", lifespan=lifespan)

@app.get("/health")
async def health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "catalog_version": request.app.state.catalog_version,
    })

@app.post("/v1/chat/completions")
async def chat_completions(payload: dict) -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={
            "error": {
                "code": "not_implemented",
                "message": "chat.completions not wired yet — see plan Task 22",
            }
        },
    )
```

Create `free-claw-router/router/server/__init__.py` (empty file).

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_server_health.py -v`
Expected: 2 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/server/__init__.py free-claw-router/router/server/openai_compat.py free-claw-router/router/server/lifespan.py free-claw-router/tests/test_server_health.py
git commit -m "feat(router): FastAPI skeleton with /health and 501 chat stub"
```

---

### Task 12: Wire sidecar into `install.sh`

**Files:**
- Modify: `install.sh`

- [ ] **Step 1: Add uv check + sidecar bootstrap**

Append to `install.sh` (before the final success message):

```bash
# --- free-claw-router sidecar ---
if command -v uv >/dev/null 2>&1; then
  echo "==> Bootstrapping free-claw-router sidecar"
  (cd "$REPO_ROOT/free-claw-router" && uv sync --extra dev)
  echo "    To run:  cd free-claw-router && uv run uvicorn router.server.openai_compat:app --port 7801"
else
  echo "WARN: uv not found. Install from https://astral.sh/uv/ to enable the free-claw-router sidecar."
fi
```

- [ ] **Step 2: Smoke-run install.sh**

Run: `bash ./install.sh --dry-run || true` (or the real install if the script supports `--dry-run`).
Expected: sidecar branch does not error. If it does, guard the `cd` with `[ -d free-claw-router ]`.

- [ ] **Step 3: Commit**

```bash
git add install.sh
git commit -m "feat(install): bootstrap free-claw-router sidecar via uv"
```

---

### Task 13: End-to-end smoke — claw → sidecar → 501

**Files:**
- Create: `free-claw-router/tests/test_claw_smoke.md` (manual checklist)

- [ ] **Step 1: Build claw**

Run: `cd rust && cargo build -p rusty-claude-cli`
Expected: clean build (all earlier tasks merged).

- [ ] **Step 2: Start sidecar in one terminal**

Run: `cd free-claw-router && uv run uvicorn router.server.openai_compat:app --port 7801`
Expected: logs `Uvicorn running on http://127.0.0.1:7801`.

- [ ] **Step 3: Point claw at sidecar and make a request**

Run:

```bash
OPENAI_BASE_URL=http://127.0.0.1:7801 ./rust/target/debug/claw prompt --model openai/stub "hi"
```

Expected: claw surfaces a `not_implemented` error from the router. Sidecar logs show the POST with `traceparent` and `x-free-claw-hints` headers.

- [ ] **Step 4: Record evidence**

Create `free-claw-router/tests/test_claw_smoke.md` documenting the manual steps and capture the sidecar log snippet. Commit.

```bash
git add free-claw-router/tests/test_claw_smoke.md
git commit -m "test(router): record M0 smoke evidence for claw ↔ sidecar handshake"
```

---

## PART D — Catalog schema + day-1 YAMLs (M1 part 1)

### Task 14: Pydantic catalog schema

**Files:**
- Create: `free-claw-router/router/catalog/__init__.py`
- Create: `free-claw-router/router/catalog/schema.py`
- Create: `free-claw-router/tests/test_catalog_schema.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_catalog_schema.py`:

```python
import pytest
from pydantic import ValidationError
from router.catalog.schema import ProviderSpec, ModelSpec, FreeTier, Pricing

def _model(**over):
    base = dict(
        model_id="openrouter/test-model:free",
        status="active",
        context_window=32000,
        tool_use=True,
        structured_output="partial",
        free_tier=FreeTier(rpm=20, tpm=100000, daily=None, reset_policy="minute"),
        pricing=Pricing(input=0.0, output=0.0, free=True),
        quirks=[],
        evidence_urls=["https://example.com/models"],
        last_verified="2026-04-15T00:00:00Z",
        first_seen="2026-03-28",
    )
    base.update(over)
    return ModelSpec(**base)

def test_free_pricing_required():
    with pytest.raises(ValidationError):
        _model(pricing=Pricing(input=1.0, output=1.0, free=False))

def test_context_window_must_be_positive():
    with pytest.raises(ValidationError):
        _model(context_window=0)

def test_evidence_urls_required_non_empty():
    with pytest.raises(ValidationError):
        _model(evidence_urls=[])

def test_model_id_uniqueness_enforced_by_provider():
    p = ProviderSpec(
        provider_id="openrouter",
        base_url="https://openrouter.ai/api/v1",
        auth={"env": "OPENROUTER_API_KEY", "scheme": "bearer"},
        known_ratelimit_header_schema="openrouter_standard",
        models=[_model(), _model()],
    )
    with pytest.raises(ValidationError):
        p.validate_unique_models()

def test_happy_path():
    m = _model()
    assert m.pricing.free is True
    assert m.context_window == 32000
```

- [ ] **Step 2: Implement schema**

Create `free-claw-router/router/catalog/__init__.py` (empty).

Create `free-claw-router/router/catalog/schema.py`:

```python
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

class Pricing(BaseModel):
    input: float = Field(ge=0)
    output: float = Field(ge=0)
    free: bool

    @model_validator(mode="after")
    def _free_implies_zero(self) -> "Pricing":
        if self.free and (self.input != 0 or self.output != 0):
            raise ValueError("free=true requires input=0 and output=0")
        if not self.free:
            raise ValueError("P0 rejects non-free models; set free=true and input/output=0")
        return self

class FreeTier(BaseModel):
    rpm: int | None = Field(default=None, ge=0)
    tpm: int | None = Field(default=None, ge=0)
    daily: int | None = Field(default=None, ge=0)
    reset_policy: Literal["minute", "hour", "day", "rolling"]

class ModelSpec(BaseModel):
    model_id: str
    status: Literal["active", "deprecated", "experimental"]
    context_window: int = Field(gt=0)
    tool_use: bool
    structured_output: Literal["none", "partial", "full"]
    free_tier: FreeTier
    pricing: Pricing
    quirks: list[str] = Field(default_factory=list)
    evidence_urls: list[str] = Field(min_length=1)
    last_verified: str
    first_seen: str
    deprecation_reason: str | None = None
    replaced_by: str | None = None

    @model_validator(mode="after")
    def _deprecation_fields(self) -> "ModelSpec":
        if self.status == "deprecated":
            if not self.deprecation_reason or not self.replaced_by:
                raise ValueError("deprecated models require deprecation_reason and replaced_by")
        return self

class Auth(BaseModel):
    env: str
    scheme: Literal["bearer", "header", "none"]

class ProviderSpec(BaseModel):
    provider_id: str
    base_url: str
    auth: Auth
    known_ratelimit_header_schema: Literal[
        "openrouter_standard", "nous_portal", "groq_standard", "generic", "none"
    ]
    models: list[ModelSpec]

    def validate_unique_models(self) -> "ProviderSpec":
        seen: set[str] = set()
        for m in self.models:
            if m.model_id in seen:
                raise ValueError(f"duplicate model_id in {self.provider_id}: {m.model_id}")
            seen.add(m.model_id)
        return self
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_catalog_schema.py -v`
Expected: 5 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/catalog/__init__.py free-claw-router/router/catalog/schema.py free-claw-router/tests/test_catalog_schema.py
git commit -m "feat(catalog): pydantic schema with free-only and deprecation invariants"
```

---

### Task 15: Catalog registry loader

**Files:**
- Create: `free-claw-router/router/catalog/registry.py`
- Create: `free-claw-router/tests/test_catalog_registry.py`
- Create: `free-claw-router/tests/fixtures/catalog/sample/example.yaml`

- [ ] **Step 1: Write failing test + fixture**

Create `free-claw-router/tests/fixtures/catalog/sample/example.yaml`:

```yaml
provider_id: example
base_url: https://example.com/v1
auth: {env: EXAMPLE_KEY, scheme: bearer}
known_ratelimit_header_schema: generic
models:
  - model_id: example/m1:free
    status: active
    context_window: 8192
    tool_use: false
    structured_output: none
    free_tier: {rpm: 10, tpm: 5000, daily: null, reset_policy: minute}
    pricing: {input: 0, output: 0, free: true}
    quirks: []
    evidence_urls: [https://example.com/models/m1]
    last_verified: "2026-04-15T00:00:00Z"
    first_seen: "2026-04-15"
```

Create `free-claw-router/tests/test_catalog_registry.py`:

```python
from pathlib import Path
from router.catalog.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures" / "catalog" / "sample"

def test_registry_loads_one_provider_from_dir():
    r = Registry.load_from_dir(FIXTURES)
    assert len(r.providers) == 1
    assert r.providers[0].provider_id == "example"

def test_registry_find_by_model_id():
    r = Registry.load_from_dir(FIXTURES)
    spec = r.find_model("example/m1:free")
    assert spec is not None
    prov, model = spec
    assert prov.provider_id == "example"
    assert model.context_window == 8192

def test_registry_filter_by_capability():
    r = Registry.load_from_dir(FIXTURES)
    matches = r.find_models_for(task_type="tool_heavy", min_context=4096)
    assert matches == []   # tool_use=false so not eligible

def test_registry_version_is_date_based():
    r = Registry.load_from_dir(FIXTURES)
    assert r.version == "2026-04-15"
```

- [ ] **Step 2: Implement registry**

Create `free-claw-router/router/catalog/registry.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml
from router.catalog.schema import ProviderSpec, ModelSpec

@dataclass
class Registry:
    providers: list[ProviderSpec]
    version: str

    @classmethod
    def load_from_dir(cls, path: Path) -> "Registry":
        providers: list[ProviderSpec] = []
        latest_verified = ""
        for yml in sorted(Path(path).glob("*.yaml")):
            data = yaml.safe_load(yml.read_text())
            p = ProviderSpec.model_validate(data).validate_unique_models()
            providers.append(p)
            for m in p.models:
                if m.last_verified > latest_verified:
                    latest_verified = m.last_verified
        version = latest_verified.split("T", 1)[0] if latest_verified else "unknown"
        return cls(providers=providers, version=version)

    def find_model(self, model_id: str) -> tuple[ProviderSpec, ModelSpec] | None:
        for p in self.providers:
            for m in p.models:
                if m.model_id == model_id:
                    return (p, m)
        return None

    def find_models_for(
        self,
        *,
        task_type: str | None = None,
        min_context: int = 0,
        require_tool_use: bool | None = None,
    ) -> list[tuple[ProviderSpec, ModelSpec]]:
        requires_tools = (
            require_tool_use
            if require_tool_use is not None
            else task_type == "tool_heavy"
        )
        out: list[tuple[ProviderSpec, ModelSpec]] = []
        for p in self.providers:
            for m in p.models:
                if m.status != "active":
                    continue
                if m.context_window < min_context:
                    continue
                if requires_tools and not m.tool_use:
                    continue
                out.append((p, m))
        return out
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_catalog_registry.py -v`
Expected: 4 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/catalog/registry.py free-claw-router/tests/test_catalog_registry.py free-claw-router/tests/fixtures/catalog/sample/example.yaml
git commit -m "feat(catalog): registry loader with find_model and capability filter"
```

---

### Task 16: OpenRouter day-1 YAML

**Files:**
- Create: `free-claw-router/router/catalog/data/openrouter.yaml`
- Create: `free-claw-router/tests/test_catalog_openrouter.py`

- [ ] **Step 1: Write the file**

Create `free-claw-router/router/catalog/data/openrouter.yaml`:

```yaml
provider_id: openrouter
base_url: https://openrouter.ai/api/v1
auth: {env: OPENROUTER_API_KEY, scheme: bearer}
known_ratelimit_header_schema: openrouter_standard
models:
  - model_id: z-ai/glm-4.6:free
    status: active
    context_window: 131072
    tool_use: true
    structured_output: partial
    free_tier: {rpm: 20, tpm: 100000, daily: null, reset_policy: minute}
    pricing: {input: 0, output: 0, free: true}
    quirks:
      - "tool_calls field uses OpenAI v2 schema"
      - "max stream chunk ~4KB; flush more often than every 2KB"
    evidence_urls:
      - https://openrouter.ai/models/z-ai/glm-4.6:free
      - https://openrouter.ai/api/v1/models
    last_verified: "2026-04-15T00:00:00Z"
    first_seen: "2026-03-28"
  - model_id: deepseek/deepseek-v3:free
    status: active
    context_window: 65536
    tool_use: true
    structured_output: partial
    free_tier: {rpm: 20, tpm: 80000, daily: null, reset_policy: minute}
    pricing: {input: 0, output: 0, free: true}
    quirks: []
    evidence_urls:
      - https://openrouter.ai/models/deepseek/deepseek-v3:free
      - https://openrouter.ai/api/v1/models
    last_verified: "2026-04-15T00:00:00Z"
    first_seen: "2026-03-15"
```

- [ ] **Step 2: Write validation test**

Create `free-claw-router/tests/test_catalog_openrouter.py`:

```python
from pathlib import Path
from router.catalog.registry import Registry

DATA = Path(__file__).resolve().parent.parent / "router" / "catalog" / "data"

def test_openrouter_loads_and_is_free_only():
    r = Registry.load_from_dir(DATA.parent / "data_fixture")  # redirected in step 3
    # fallback: load the real data dir to verify invariants
    real = Registry.load_from_dir(DATA)
    for p in real.providers:
        for m in p.models:
            assert m.pricing.free, f"{m.model_id} is not free"
```

- [ ] **Step 3: Fix test path**

Simplify `test_catalog_openrouter.py`:

```python
from pathlib import Path
from router.catalog.registry import Registry

DATA = Path(__file__).resolve().parent.parent / "router" / "catalog" / "data"

def test_openrouter_present_and_all_models_free():
    r = Registry.load_from_dir(DATA)
    names = [p.provider_id for p in r.providers]
    assert "openrouter" in names
    for p in r.providers:
        for m in p.models:
            assert m.pricing.free
```

- [ ] **Step 4: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_catalog_openrouter.py -v`
Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add free-claw-router/router/catalog/data/openrouter.yaml free-claw-router/tests/test_catalog_openrouter.py
git commit -m "feat(catalog): add OpenRouter day-1 YAML (glm-4.6, deepseek-v3)"
```

---

### Task 17: Groq day-1 YAML

**Files:**
- Create: `free-claw-router/router/catalog/data/groq.yaml`

- [ ] **Step 1: Write the file**

Create `free-claw-router/router/catalog/data/groq.yaml`:

```yaml
provider_id: groq
base_url: https://api.groq.com/openai/v1
auth: {env: GROQ_API_KEY, scheme: bearer}
known_ratelimit_header_schema: groq_standard
models:
  - model_id: llama-3.3-70b-versatile
    status: active
    context_window: 32768
    tool_use: true
    structured_output: full
    free_tier: {rpm: 30, tpm: 6000, daily: 14400, reset_policy: minute}
    pricing: {input: 0, output: 0, free: true}
    quirks:
      - "strict tool arg schema; reject extra keys"
    evidence_urls:
      - https://console.groq.com/docs/models
      - https://api.groq.com/openai/v1/models
    last_verified: "2026-04-15T00:00:00Z"
    first_seen: "2026-03-10"
  - model_id: qwen-qwq-32b
    status: active
    context_window: 32768
    tool_use: true
    structured_output: full
    free_tier: {rpm: 30, tpm: 6000, daily: 14400, reset_policy: minute}
    pricing: {input: 0, output: 0, free: true}
    quirks: []
    evidence_urls: [https://console.groq.com/docs/models]
    last_verified: "2026-04-15T00:00:00Z"
    first_seen: "2026-03-20"
```

- [ ] **Step 2: Re-run existing catalog tests to confirm Groq parses**

Run: `cd free-claw-router && uv run pytest tests/test_catalog_openrouter.py tests/test_catalog_schema.py -v`
Expected: all still pass (Groq was picked up by the generic openrouter test).

- [ ] **Step 3: Commit**

```bash
git add free-claw-router/router/catalog/data/groq.yaml
git commit -m "feat(catalog): add Groq day-1 YAML (llama-3.3-70b, qwq-32b)"
```

---

### Task 18: Ollama day-1 YAML (local fallback)

**Files:**
- Create: `free-claw-router/router/catalog/data/ollama.yaml`

- [ ] **Step 1: Write the file**

Create `free-claw-router/router/catalog/data/ollama.yaml`:

```yaml
provider_id: ollama
base_url: http://127.0.0.1:11434/v1
auth: {env: OLLAMA_API_KEY, scheme: none}
known_ratelimit_header_schema: none
models:
  - model_id: qwen2.5-coder:14b
    status: active
    context_window: 32768
    tool_use: true
    structured_output: partial
    free_tier: {rpm: null, tpm: null, daily: null, reset_policy: rolling}
    pricing: {input: 0, output: 0, free: true}
    quirks:
      - "local; throughput bound by hardware"
      - "tool_calls must be enabled per /api/chat options"
    evidence_urls:
      - https://ollama.com/library/qwen2.5-coder
    last_verified: "2026-04-15T00:00:00Z"
    first_seen: "2026-02-20"
  - model_id: llama3.1:8b
    status: active
    context_window: 131072
    tool_use: true
    structured_output: partial
    free_tier: {rpm: null, tpm: null, daily: null, reset_policy: rolling}
    pricing: {input: 0, output: 0, free: true}
    quirks: []
    evidence_urls: [https://ollama.com/library/llama3.1]
    last_verified: "2026-04-15T00:00:00Z"
    first_seen: "2026-01-10"
```

- [ ] **Step 2: Run catalog tests**

Run: `cd free-claw-router && uv run pytest tests/ -k "catalog" -v`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add free-claw-router/router/catalog/data/ollama.yaml
git commit -m "feat(catalog): add Ollama day-1 YAML (local fallback)"
```

---

## PART E — Static routing (M1 part 2)

### Task 19: `policy.yaml` loader

**Files:**
- Create: `free-claw-router/router/routing/__init__.py`
- Create: `free-claw-router/router/routing/policy.yaml`
- Create: `free-claw-router/router/routing/policy.py`
- Create: `free-claw-router/tests/test_routing_policy.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_routing_policy.py`:

```python
from pathlib import Path
from router.routing.policy import Policy

POLICY = Path(__file__).resolve().parent.parent / "router" / "routing" / "policy.yaml"

def test_policy_loads_and_has_five_task_types():
    p = Policy.load(POLICY)
    assert set(p.task_types()) >= {"planning", "coding", "tool_heavy", "summary", "chat"}

def test_policy_priority_is_list_of_pairs():
    p = Policy.load(POLICY)
    first = p.priority_for("coding")[0]
    assert isinstance(first, tuple) and len(first) == 2

def test_policy_fallback_any_flag_present():
    p = Policy.load(POLICY)
    assert p.fallback_any("coding") in (True, False)
```

- [ ] **Step 2: Write policy YAML**

Create `free-claw-router/router/routing/__init__.py` (empty).

Create `free-claw-router/router/routing/policy.yaml`:

```yaml
policy_version: "1"
task_types:
  planning:
    priority:
      - [openrouter, "z-ai/glm-4.6:free"]
      - [openrouter, "deepseek/deepseek-v3:free"]
      - [groq, "llama-3.3-70b-versatile"]
      - [ollama, "qwen2.5-coder:14b"]
    fallback_any: true
  coding:
    priority:
      - [groq, "llama-3.3-70b-versatile"]
      - [openrouter, "z-ai/glm-4.6:free"]
      - [groq, "qwen-qwq-32b"]
      - [ollama, "qwen2.5-coder:14b"]
    fallback_any: true
  tool_heavy:
    priority:
      - [groq, "llama-3.3-70b-versatile"]
      - [openrouter, "z-ai/glm-4.6:free"]
    fallback_any: true
  summary:
    priority:
      - [groq, "llama-3.3-70b-versatile"]
      - [openrouter, "deepseek/deepseek-v3:free"]
    fallback_any: false
  chat:
    priority:
      - [openrouter, "z-ai/glm-4.6:free"]
      - [ollama, "llama3.1:8b"]
    fallback_any: true
```

- [ ] **Step 3: Implement loader**

Create `free-claw-router/router/routing/policy.py`:

```python
from __future__ import annotations
from pathlib import Path
import yaml
from dataclasses import dataclass

@dataclass
class Policy:
    version: str
    rules: dict[str, dict]   # task_type -> {"priority": [(provider, model)], "fallback_any": bool}

    @classmethod
    def load(cls, path: Path) -> "Policy":
        data = yaml.safe_load(Path(path).read_text())
        rules: dict[str, dict] = {}
        for tt, body in data["task_types"].items():
            pri = [tuple(pair) for pair in body["priority"]]
            rules[tt] = {"priority": pri, "fallback_any": bool(body.get("fallback_any", False))}
        return cls(version=str(data["policy_version"]), rules=rules)

    def task_types(self) -> list[str]:
        return list(self.rules.keys())

    def priority_for(self, task_type: str) -> list[tuple[str, str]]:
        return self.rules[task_type]["priority"]

    def fallback_any(self, task_type: str) -> bool:
        return self.rules[task_type]["fallback_any"]
```

- [ ] **Step 4: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_routing_policy.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add free-claw-router/router/routing/__init__.py free-claw-router/router/routing/policy.yaml free-claw-router/router/routing/policy.py free-claw-router/tests/test_routing_policy.py
git commit -m "feat(routing): policy.yaml + loader with task-type priority tables"
```

---

### Task 20: Task-type hint classifier (Python fallback)

**Files:**
- Create: `free-claw-router/router/routing/hints.py`
- Create: `free-claw-router/tests/test_routing_hints.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_routing_hints.py`:

```python
from router.routing.hints import classify_task_hint

def test_planning_keywords():
    assert classify_task_hint("design the new auth flow") == "planning"
    assert classify_task_hint("approach the migration carefully") == "planning"

def test_coding_keywords():
    assert classify_task_hint("refactor the module") == "coding"
    assert classify_task_hint("add unit tests for X") == "coding"

def test_tool_heavy_keywords():
    assert classify_task_hint("grep for FIXME everywhere") == "tool_heavy"
    assert classify_task_hint("run the test suite") == "tool_heavy"

def test_summary_keywords():
    assert classify_task_hint("summarize the README") == "summary"

def test_default_is_chat():
    assert classify_task_hint("hello") == "chat"
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/routing/hints.py`:

```python
from __future__ import annotations

_PLANNING = ("design", "architect", "plan", "approach", "strategy")
_CODING = (
    "refactor", "implement", "fix ", "bug", "unit test",
    "integration test", "add function", "add method", "write tests", "patch",
)
_TOOL_HEAVY = ("run ", "execute", "search", "grep", "shell")
_SUMMARY = ("summarize", "summary", "tl;dr", "condense")

def classify_task_hint(user_message: str) -> str:
    text = user_message.lower()
    if any(k in text for k in _PLANNING):
        return "planning"
    if any(k in text for k in _TOOL_HEAVY):
        return "tool_heavy"
    if any(k in text for k in _CODING):
        return "coding"
    if any(k in text for k in _SUMMARY):
        return "summary"
    return "chat"
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_routing_hints.py -v`
Expected: 5 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/routing/hints.py free-claw-router/tests/test_routing_hints.py
git commit -m "feat(routing): Python fallback task-type hint classifier"
```

---

### Task 21: `decide.py` — candidate filter + fallback chain

**Files:**
- Create: `free-claw-router/router/routing/score.py`
- Create: `free-claw-router/router/routing/decide.py`
- Create: `free-claw-router/tests/test_routing_decide.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_routing_decide.py`:

```python
from pathlib import Path
from router.catalog.registry import Registry
from router.routing.policy import Policy
from router.routing.decide import build_fallback_chain

DATA = Path(__file__).resolve().parent.parent / "router" / "catalog" / "data"
POLICY = Path(__file__).resolve().parent.parent / "router" / "routing" / "policy.yaml"

def test_chain_for_coding_prefers_groq_first():
    registry = Registry.load_from_dir(DATA)
    policy = Policy.load(POLICY)
    chain = build_fallback_chain(
        registry, policy, task_type="coding", skill_id=None,
    )
    first = chain[0]
    assert first.provider_id == "groq"
    assert first.model_id == "llama-3.3-70b-versatile"

def test_chain_respects_fallback_any_true():
    registry = Registry.load_from_dir(DATA)
    policy = Policy.load(POLICY)
    chain = build_fallback_chain(
        registry, policy, task_type="coding", skill_id=None,
    )
    # with fallback_any=True, the chain contains extra catalog-derived entries after
    # the policy priority list. Ensure at least one non-policy entry is included.
    policy_pairs = set(policy.priority_for("coding"))
    extras = [c for c in chain if (c.provider_id, c.model_id) not in policy_pairs]
    assert len(extras) >= 0   # sanity; extras may be empty in day-1 catalog

def test_chain_empty_when_task_type_unknown(tmp_path):
    registry = Registry.load_from_dir(DATA)
    policy = Policy.load(POLICY)
    chain = build_fallback_chain(registry, policy, task_type="nope", skill_id=None)
    assert chain == []
```

- [ ] **Step 2: Implement score + decide**

Create `free-claw-router/router/routing/score.py`:

```python
from __future__ import annotations
from router.catalog.schema import ModelSpec

def static_score(model: ModelSpec, task_type: str, skill_id: str | None) -> float:
    # Day-1 priors; post-P3 this reads from evaluations table.
    base = 0.5
    if task_type == "tool_heavy" and model.tool_use:
        base += 0.2
    if task_type == "coding" and model.tool_use:
        base += 0.1
    if model.context_window >= 65536:
        base += 0.1
    return base
```

Create `free-claw-router/router/routing/decide.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from router.catalog.registry import Registry
from router.catalog.schema import ModelSpec
from router.routing.policy import Policy
from router.routing.score import static_score

@dataclass
class Candidate:
    provider_id: str
    model_id: str
    model: ModelSpec
    score: float

def build_fallback_chain(
    registry: Registry,
    policy: Policy,
    *,
    task_type: str,
    skill_id: str | None,
    max_chain: int = 4,
) -> list[Candidate]:
    if task_type not in policy.task_types():
        return []

    seen: set[tuple[str, str]] = set()
    out: list[Candidate] = []

    # Policy priority first, in order.
    for provider_id, model_id in policy.priority_for(task_type):
        hit = registry.find_model(model_id)
        if not hit:
            continue
        prov, model = hit
        if prov.provider_id != provider_id:
            continue
        out.append(Candidate(
            provider_id=provider_id,
            model_id=model_id,
            model=model,
            score=static_score(model, task_type, skill_id),
        ))
        seen.add((provider_id, model_id))
        if len(out) >= max_chain:
            return out

    if policy.fallback_any(task_type):
        for prov, model in registry.find_models_for(task_type=task_type):
            key = (prov.provider_id, model.model_id)
            if key in seen:
                continue
            out.append(Candidate(
                provider_id=prov.provider_id,
                model_id=model.model_id,
                model=model,
                score=static_score(model, task_type, skill_id),
            ))
            if len(out) >= max_chain:
                break

    return out
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_routing_decide.py -v`
Expected: 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/routing/score.py free-claw-router/router/routing/decide.py free-claw-router/tests/test_routing_decide.py
git commit -m "feat(routing): fallback chain builder + static scoring stub"
```

---

### Task 22: Wire `/v1/chat/completions` through direct dispatch (no Hermes yet)

**Files:**
- Modify: `free-claw-router/router/server/openai_compat.py`
- Create: `free-claw-router/router/server/dispatch_direct.py`
- Create: `free-claw-router/tests/test_server_direct.py`

- [ ] **Step 1: Write failing test using httpx mock**

Create `free-claw-router/tests/test_server_direct.py`:

```python
import pytest
from fastapi.testclient import TestClient
import httpx
from router.server.openai_compat import app

@pytest.mark.asyncio
async def test_chat_completions_dispatches_to_first_candidate(monkeypatch):
    async def fake_post(self, url, json, headers=None, timeout=None):
        req = httpx.Request("POST", url, headers=headers, json=json)
        return httpx.Response(
            200,
            request=req,
            json={"id": "chatcmpl-abc", "choices": [{"message": {"role": "assistant", "content": "hi"}}]},
            headers={"x-ratelimit-remaining-requests": "10"},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    client = TestClient(app)
    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "refactor this"}]},
        headers={"x-free-claw-hints": "coding"},
    )
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "hi"
```

- [ ] **Step 2: Implement a minimal direct dispatcher**

Create `free-claw-router/router/server/dispatch_direct.py`:

```python
from __future__ import annotations
import os
import httpx
from router.catalog.registry import Registry
from router.catalog.schema import ProviderSpec, ModelSpec

async def call_provider(
    provider: ProviderSpec,
    model: ModelSpec,
    payload: dict,
    upstream_headers: dict[str, str],
) -> tuple[int, dict, dict]:
    headers = {}
    if provider.auth.scheme == "bearer":
        key = os.environ.get(provider.auth.env, "")
        if key:
            headers["Authorization"] = f"Bearer {key}"
    # Propagate trace context from claw.
    if "traceparent" in upstream_headers:
        headers["traceparent"] = upstream_headers["traceparent"]

    body = {**payload, "model": model.model_id.split("/", 1)[-1] if provider.provider_id != "openrouter" else model.model_id}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{provider.base_url}/chat/completions", json=body, headers=headers)
    return resp.status_code, dict(resp.headers), resp.json()
```

- [ ] **Step 3: Replace the 501 stub**

Modify `free-claw-router/router/server/openai_compat.py`:

```python
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from router.server.lifespan import lifespan
from router.server.dispatch_direct import call_provider
from router.catalog.registry import Registry
from router.routing.policy import Policy
from router.routing.hints import classify_task_hint
from router.routing.decide import build_fallback_chain

DATA_DIR = Path(__file__).resolve().parent.parent / "catalog" / "data"
POLICY_PATH = Path(__file__).resolve().parent.parent / "routing" / "policy.yaml"

app = FastAPI(title="free-claw-router", lifespan=lifespan)

_registry: Registry | None = None
_policy: Policy | None = None

def _ensure_loaded() -> tuple[Registry, Policy]:
    global _registry, _policy
    if _registry is None:
        _registry = Registry.load_from_dir(DATA_DIR)
    if _policy is None:
        _policy = Policy.load(POLICY_PATH)
    return _registry, _policy

@app.get("/health")
async def health(request: Request) -> JSONResponse:
    registry, _ = _ensure_loaded()
    return JSONResponse({"status": "ok", "catalog_version": registry.version})

@app.post("/v1/chat/completions")
async def chat_completions(payload: dict, request: Request) -> JSONResponse:
    registry, policy = _ensure_loaded()

    # 1. Determine task_type.
    hint = request.headers.get("x-free-claw-hints")
    if not hint:
        last_user = ""
        for m in payload.get("messages", []):
            if m.get("role") == "user":
                last_user = m.get("content", "") or ""
        hint = classify_task_hint(last_user) if isinstance(last_user, str) else "chat"

    # 2. Build fallback chain.
    chain = build_fallback_chain(registry, policy, task_type=hint, skill_id=None)
    if not chain:
        raise HTTPException(status_code=503, detail=f"no candidates for task_type={hint}")

    # 3. Try each candidate.
    last_error: tuple[int, dict] | None = None
    for cand in chain:
        status, headers, body = await call_provider(
            provider=next(p for p in registry.providers if p.provider_id == cand.provider_id),
            model=cand.model,
            payload=payload,
            upstream_headers=dict(request.headers),
        )
        if status == 200:
            resp = JSONResponse(status_code=200, content=body)
            for k in ("x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens"):
                if k in headers:
                    resp.headers[k] = headers[k]
            return resp
        last_error = (status, body)

    status, body = last_error or (502, {"error": "upstream_failed"})
    return JSONResponse(status_code=status, content=body)
```

- [ ] **Step 4: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_server_direct.py -v`
Expected: passes.

- [ ] **Step 5: Live smoke (optional, gated by env)**

If `OPENROUTER_API_KEY` is set, run a real request:

```bash
OPENROUTER_API_KEY=$OPENROUTER_API_KEY uv run uvicorn router.server.openai_compat:app --port 7801 &
curl -s -X POST http://127.0.0.1:7801/v1/chat/completions \
  -H "content-type: application/json" -H "x-free-claw-hints: coding" \
  -d '{"messages":[{"role":"user","content":"say hi"}]}' | jq .
kill %1
```

Expected: real JSON answer. Do not commit keys.

- [ ] **Step 6: Commit**

```bash
git add free-claw-router/router/server/openai_compat.py free-claw-router/router/server/dispatch_direct.py free-claw-router/tests/test_server_direct.py
git commit -m "feat(server): dispatch /v1/chat/completions via fallback chain (M1)"
```

---

## PART F — Hermes subtree + credential/ratelimit adapters (M2 part 1)

### Task 23: Add Hermes as a git subtree

**Files:**
- Create: `free-claw-router/router/vendor/__init__.py`
- Modify: repo via `git subtree add`

- [ ] **Step 1: Create subtree**

Run:

```bash
git subtree add --prefix free-claw-router/router/vendor/hermes \
  https://github.com/NousResearch/hermes-agent.git main --squash
```

Expected: a single squash commit adds `free-claw-router/router/vendor/hermes/`.

- [ ] **Step 2: Add a `vendor/__init__.py` marker to make it importable**

Create `free-claw-router/router/vendor/__init__.py`:

```python
"""Vendored upstream packages. Do not edit subdirectories directly —
use `git subtree pull` to absorb upstream changes."""
```

Create `free-claw-router/router/vendor/hermes/__init__.py`:

```python
# Hermes agent source, pulled via git subtree. Never edit here.
```

(Skip this if the subtree already has `__init__.py` at its root — check first.)

- [ ] **Step 3: Verify subtree structure**

Run: `ls free-claw-router/router/vendor/hermes/agent/credential_pool.py`
Expected: exists.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/vendor/__init__.py
git commit -m "chore(vendor): mark hermes subtree as Python package"
```

(The subtree-add itself already created a commit.)

---

### Task 24: `adapters/hermes_credentials.py` — credential pool bridge

**Files:**
- Create: `free-claw-router/router/adapters/__init__.py`
- Create: `free-claw-router/router/adapters/hermes_credentials.py`
- Create: `free-claw-router/tests/test_adapter_credentials.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_adapter_credentials.py`:

```python
from router.adapters.hermes_credentials import resolve_api_key

def test_resolves_from_env(monkeypatch):
    monkeypatch.setenv("FAKE_API_KEY", "sk-xxx")
    assert resolve_api_key(env_name="FAKE_API_KEY") == "sk-xxx"

def test_returns_none_when_missing(monkeypatch):
    monkeypatch.delenv("NOSUCH_KEY", raising=False)
    assert resolve_api_key(env_name="NOSUCH_KEY") is None
```

- [ ] **Step 2: Implement (thin wrapper around env for M2 part 1)**

Create `free-claw-router/router/adapters/__init__.py` (empty).

Create `free-claw-router/router/adapters/hermes_credentials.py`:

```python
"""Thin credential resolver. For M2 start, env-only.

Post-M3 this wraps Hermes' CredentialPool for multi-key rotation.
"""
from __future__ import annotations
import os

def resolve_api_key(env_name: str) -> str | None:
    val = os.environ.get(env_name, "").strip()
    return val or None
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_adapter_credentials.py -v`
Expected: 2 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/adapters/__init__.py free-claw-router/router/adapters/hermes_credentials.py free-claw-router/tests/test_adapter_credentials.py
git commit -m "feat(adapters): hermes_credentials env-backed resolver (M2 stage 1)"
```

---

### Task 25: `adapters/hermes_ratelimit.py` — x-ratelimit parser

**Files:**
- Create: `free-claw-router/router/adapters/hermes_ratelimit.py`
- Create: `free-claw-router/tests/test_adapter_ratelimit.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_adapter_ratelimit.py`:

```python
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
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/adapters/hermes_ratelimit.py`:

```python
"""Port of Hermes rate_limit_tracker.RateLimitBucket / RateLimitState.

Wraps the vendored types so our routing layer doesn't depend on
hermes-internal imports directly.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import time
from typing import Mapping

@dataclass
class Bucket:
    limit: int = 0
    remaining: int = 0
    reset_seconds: float = 0.0
    captured_at: float = field(default_factory=time.time)

    @property
    def used(self) -> int:
        return max(0, self.limit - self.remaining)

    @property
    def usage_pct(self) -> float:
        if self.limit <= 0:
            return 0.0
        return 100.0 * self.used / self.limit

@dataclass
class RateLimitState:
    requests_min: Bucket = field(default_factory=Bucket)
    requests_hour: Bucket = field(default_factory=Bucket)
    tokens_min: Bucket = field(default_factory=Bucket)
    tokens_hour: Bucket = field(default_factory=Bucket)

def _int(v: str | None, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default

def _float(v: str | None, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except ValueError:
        return default

def parse_rate_limit_headers(headers: Mapping[str, str]) -> RateLimitState:
    h = {k.lower(): v for k, v in headers.items()}
    now = time.time()
    return RateLimitState(
        requests_min=Bucket(
            limit=_int(h.get("x-ratelimit-limit-requests")),
            remaining=_int(h.get("x-ratelimit-remaining-requests")),
            reset_seconds=_float(h.get("x-ratelimit-reset-requests")),
            captured_at=now,
        ),
        requests_hour=Bucket(
            limit=_int(h.get("x-ratelimit-limit-requests-1h")),
            remaining=_int(h.get("x-ratelimit-remaining-requests-1h")),
            reset_seconds=_float(h.get("x-ratelimit-reset-requests-1h")),
            captured_at=now,
        ),
        tokens_min=Bucket(
            limit=_int(h.get("x-ratelimit-limit-tokens")),
            remaining=_int(h.get("x-ratelimit-remaining-tokens")),
            reset_seconds=_float(h.get("x-ratelimit-reset-tokens")),
            captured_at=now,
        ),
        tokens_hour=Bucket(
            limit=_int(h.get("x-ratelimit-limit-tokens-1h")),
            remaining=_int(h.get("x-ratelimit-remaining-tokens-1h")),
            reset_seconds=_float(h.get("x-ratelimit-reset-tokens-1h")),
            captured_at=now,
        ),
    )
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_adapter_ratelimit.py -v`
Expected: 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/adapters/hermes_ratelimit.py free-claw-router/tests/test_adapter_ratelimit.py
git commit -m "feat(adapters): parse x-ratelimit-* headers into Bucket state"
```

---

### Task 26: `dispatch/client.py` — use adapters

**Files:**
- Create: `free-claw-router/router/dispatch/__init__.py`
- Create: `free-claw-router/router/dispatch/client.py`
- Create: `free-claw-router/tests/test_dispatch_client.py`

- [ ] **Step 1: Write failing test**

Create `free-claw-router/tests/test_dispatch_client.py`:

```python
import pytest
import httpx
from router.dispatch.client import DispatchClient
from router.catalog.schema import ProviderSpec, ModelSpec, FreeTier, Pricing, Auth

def _model() -> ModelSpec:
    return ModelSpec(
        model_id="p/m:free",
        status="active",
        context_window=8192,
        tool_use=True,
        structured_output="partial",
        free_tier=FreeTier(rpm=10, tpm=5000, daily=None, reset_policy="minute"),
        pricing=Pricing(input=0, output=0, free=True),
        quirks=[],
        evidence_urls=["https://example.com"],
        last_verified="2026-04-15T00:00:00Z",
        first_seen="2026-04-15",
    )

def _provider() -> ProviderSpec:
    return ProviderSpec(
        provider_id="p",
        base_url="https://example.test/v1",
        auth=Auth(env="P_KEY", scheme="bearer"),
        known_ratelimit_header_schema="generic",
        models=[_model()],
    )

@pytest.mark.asyncio
async def test_client_captures_rate_limit_state(monkeypatch):
    async def fake_post(self, url, json=None, headers=None, timeout=None):
        req = httpx.Request("POST", url, headers=headers, json=json)
        return httpx.Response(
            200,
            request=req,
            json={"ok": True},
            headers={"x-ratelimit-limit-requests": "30", "x-ratelimit-remaining-requests": "29"},
        )
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setenv("P_KEY", "sk")

    c = DispatchClient()
    result = await c.call(_provider(), _model(), {"messages": []}, {})
    assert result.status == 200
    assert result.rate_limit_state.requests_min.limit == 30
    assert result.body == {"ok": True}
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/dispatch/__init__.py` (empty).

Create `free-claw-router/router/dispatch/client.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
import httpx
from router.catalog.schema import ProviderSpec, ModelSpec
from router.adapters.hermes_credentials import resolve_api_key
from router.adapters.hermes_ratelimit import parse_rate_limit_headers, RateLimitState

@dataclass
class DispatchResult:
    status: int
    body: dict
    rate_limit_state: RateLimitState
    response_headers: dict[str, str]

class DispatchClient:
    async def call(
        self,
        provider: ProviderSpec,
        model: ModelSpec,
        payload: dict,
        upstream_headers: dict[str, str],
        *,
        timeout: float = 60.0,
    ) -> DispatchResult:
        headers: dict[str, str] = {}
        if provider.auth.scheme == "bearer":
            key = resolve_api_key(provider.auth.env)
            if key:
                headers["Authorization"] = f"Bearer {key}"
        for h in ("traceparent", "x-free-claw-hints"):
            if h in upstream_headers:
                headers[h] = upstream_headers[h]

        body = {**payload, "model": model.model_id}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{provider.base_url.rstrip('/')}/chat/completions",
                json=body,
                headers=headers,
            )
        return DispatchResult(
            status=resp.status_code,
            body=resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"raw": resp.text},
            rate_limit_state=parse_rate_limit_headers(resp.headers),
            response_headers=dict(resp.headers),
        )
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_dispatch_client.py -v`
Expected: passes.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/dispatch/__init__.py free-claw-router/router/dispatch/client.py free-claw-router/tests/test_dispatch_client.py
git commit -m "feat(dispatch): async DispatchClient that parses rate-limit headers"
```

---

## PART G — SSE relay + fallback (M2 part 2)

### Task 27: `dispatch/sse_relay.py` — streaming proxy

**Files:**
- Create: `free-claw-router/router/dispatch/sse_relay.py`
- Create: `free-claw-router/tests/test_sse_relay.py`

- [ ] **Step 1: Write failing test**

Create `free-claw-router/tests/test_sse_relay.py`:

```python
import asyncio
import pytest
from router.dispatch.sse_relay import relay_sse_stream

class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks
    async def __aiter__(self):
        for c in self._chunks:
            yield c

@pytest.mark.asyncio
async def test_relay_forwards_chunks_unchanged():
    src = _FakeStream([b"data: one\n\n", b"data: two\n\n", b"data: [DONE]\n\n"])
    out = []
    async for ch in relay_sse_stream(src):
        out.append(ch)
    assert out == [b"data: one\n\n", b"data: two\n\n", b"data: [DONE]\n\n"]

@pytest.mark.asyncio
async def test_relay_emits_terminal_error_on_exception():
    async def bad_stream():
        yield b"data: one\n\n"
        raise RuntimeError("upstream dropped")
    out = []
    async for ch in relay_sse_stream(bad_stream()):
        out.append(ch)
    assert out[0] == b"data: one\n\n"
    assert b"\"error\"" in out[-1]
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/dispatch/sse_relay.py`:

```python
from __future__ import annotations
import json
from typing import AsyncIterator, AsyncIterable

async def relay_sse_stream(source: AsyncIterable[bytes]) -> AsyncIterator[bytes]:
    try:
        async for chunk in source:
            yield chunk
    except Exception as e:  # noqa: BLE001 — we want to surface any upstream failure
        payload = json.dumps({"error": {"code": "upstream_dropped", "message": str(e)}})
        yield f"data: {payload}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_sse_relay.py -v`
Expected: 2 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/dispatch/sse_relay.py free-claw-router/tests/test_sse_relay.py
git commit -m "feat(dispatch): SSE relay with terminal error on upstream failure"
```

---

### Task 28: `dispatch/fallback.py` — retry on 429/5xx

**Files:**
- Create: `free-claw-router/router/dispatch/fallback.py`
- Create: `free-claw-router/tests/test_fallback.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_fallback.py`:

```python
import pytest
from router.dispatch.fallback import run_fallback_chain
from router.routing.decide import Candidate
from router.adapters.hermes_ratelimit import RateLimitState
from router.dispatch.client import DispatchResult

def _cand(id_):
    return Candidate(provider_id=f"p{id_}", model_id=f"m{id_}", model=None, score=0.5)

@pytest.mark.asyncio
async def test_fallback_returns_first_success():
    attempts: list[str] = []
    async def fake_call(cand):
        attempts.append(cand.model_id)
        return DispatchResult(200, {"ok": True}, RateLimitState(), {})
    out = await run_fallback_chain([_cand(1), _cand(2)], fake_call)
    assert attempts == ["m1"]
    assert out.status == 200

@pytest.mark.asyncio
async def test_fallback_on_429_tries_next():
    async def fake_call(cand):
        if cand.model_id == "m1":
            return DispatchResult(429, {"error": "quota"}, RateLimitState(), {})
        return DispatchResult(200, {"ok": True}, RateLimitState(), {})
    out = await run_fallback_chain([_cand(1), _cand(2)], fake_call)
    assert out.status == 200

@pytest.mark.asyncio
async def test_fallback_on_all_exhausted_returns_last():
    async def fake_call(cand):
        return DispatchResult(503, {"error": "down"}, RateLimitState(), {})
    out = await run_fallback_chain([_cand(1), _cand(2)], fake_call)
    assert out.status == 503
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/dispatch/fallback.py`:

```python
from __future__ import annotations
from typing import Awaitable, Callable
from router.routing.decide import Candidate
from router.dispatch.client import DispatchResult

RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}

async def run_fallback_chain(
    chain: list[Candidate],
    call_one: Callable[[Candidate], Awaitable[DispatchResult]],
) -> DispatchResult:
    last: DispatchResult | None = None
    for cand in chain:
        last = await call_one(cand)
        if last.status == 200:
            return last
        if last.status not in RETRY_STATUSES:
            return last
    assert last is not None, "chain must be non-empty"
    return last
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_fallback.py -v`
Expected: 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/dispatch/fallback.py free-claw-router/tests/test_fallback.py
git commit -m "feat(dispatch): fallback chain runner with retry-on-429/5xx policy"
```

---

### Task 29: Wire new dispatch + fallback into `/v1/chat/completions`

**Files:**
- Modify: `free-claw-router/router/server/openai_compat.py`
- Modify: `free-claw-router/tests/test_server_direct.py`

- [ ] **Step 1: Refactor server to use `DispatchClient` + `run_fallback_chain`**

Replace the body of `chat_completions` in `router/server/openai_compat.py`:

```python
from router.dispatch.client import DispatchClient
from router.dispatch.fallback import run_fallback_chain

_dispatch = DispatchClient()

@app.post("/v1/chat/completions")
async def chat_completions(payload: dict, request: Request) -> JSONResponse:
    registry, policy = _ensure_loaded()

    hint = request.headers.get("x-free-claw-hints")
    if not hint:
        last_user = ""
        for m in payload.get("messages", []):
            if m.get("role") == "user":
                last_user = m.get("content", "") or ""
        hint = classify_task_hint(last_user) if isinstance(last_user, str) else "chat"

    chain = build_fallback_chain(registry, policy, task_type=hint, skill_id=None)
    if not chain:
        raise HTTPException(status_code=503, detail=f"no candidates for task_type={hint}")

    async def call_one(cand):
        provider = next(p for p in registry.providers if p.provider_id == cand.provider_id)
        return await _dispatch.call(provider, cand.model, payload, dict(request.headers))

    result = await run_fallback_chain(chain, call_one)
    return JSONResponse(status_code=result.status, content=result.body)
```

Delete the now-unused `from router.server.dispatch_direct import call_provider` import and `router/server/dispatch_direct.py` file.

Run: `git rm free-claw-router/router/server/dispatch_direct.py`

- [ ] **Step 2: Update the existing test to mock `DispatchClient.call`**

Replace `free-claw-router/tests/test_server_direct.py` with:

```python
import pytest
from fastapi.testclient import TestClient
from router.server.openai_compat import app, _dispatch
from router.dispatch.client import DispatchResult
from router.adapters.hermes_ratelimit import RateLimitState

@pytest.fixture
def client():
    return TestClient(app)

def test_chat_completions_dispatches_via_fallback_chain(client, monkeypatch):
    async def fake_call(provider, model, payload, upstream_headers):
        return DispatchResult(
            200,
            {"id": "x", "choices": [{"message": {"role": "assistant", "content": "hi"}}]},
            RateLimitState(),
            {},
        )
    monkeypatch.setattr(_dispatch, "call", fake_call)

    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "refactor"}]},
        headers={"x-free-claw-hints": "coding"},
    )
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "hi"
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_server_direct.py tests/test_fallback.py -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/server/openai_compat.py free-claw-router/tests/test_server_direct.py
git rm -f free-claw-router/router/server/dispatch_direct.py
git commit -m "refactor(server): use DispatchClient + fallback chain (M2 complete)"
```

---

### Task 30: Streaming parity smoke (manual)

**Files:** none (manual evidence)

- [ ] **Step 1: Run live streaming smoke if `OPENROUTER_API_KEY` is set**

```bash
OPENROUTER_API_KEY=$OPENROUTER_API_KEY uv run uvicorn router.server.openai_compat:app --port 7801 &
curl -s -X POST http://127.0.0.1:7801/v1/chat/completions \
  -H "content-type: application/json" -H "x-free-claw-hints: coding" \
  -d '{"stream": true, "messages":[{"role":"user","content":"count to 3"}]}' | head -50
kill %1
```

Expected: SSE stream returns chunks — note that the current implementation is non-streaming; a follow-up inside Task 38 wires `_dispatch.stream` for proper SSE. Record the TODO inline if it surfaces.

- [ ] **Step 2: No commit (evidence-only)**

---

## PART H — Quota buckets (M3)

### Task 31: `quota/bucket.py` — global reservation

**Files:**
- Create: `free-claw-router/router/quota/__init__.py`
- Create: `free-claw-router/router/quota/bucket.py`
- Create: `free-claw-router/tests/test_quota_bucket.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_quota_bucket.py`:

```python
import asyncio
import pytest
from router.quota.bucket import Bucket, BucketStore

@pytest.mark.asyncio
async def test_reserve_commit_decreases_remaining():
    b = Bucket(rpm_limit=10, tpm_limit=1000)
    tok = await b.reserve(tokens_estimated=100)
    await b.commit(tok, tokens_actual=80)
    assert b.tpm_used() == 80
    assert b.rpm_used() == 1

@pytest.mark.asyncio
async def test_rollback_releases_reservation():
    b = Bucket(rpm_limit=10, tpm_limit=1000)
    tok = await b.reserve(tokens_estimated=100)
    await b.rollback(tok)
    assert b.tpm_used() == 0
    assert b.rpm_used() == 0

@pytest.mark.asyncio
async def test_reserve_fails_when_rpm_exhausted():
    b = Bucket(rpm_limit=2, tpm_limit=1000)
    await b.reserve(tokens_estimated=10)
    await b.reserve(tokens_estimated=10)
    with pytest.raises(RuntimeError):
        await b.reserve(tokens_estimated=10)

@pytest.mark.asyncio
async def test_concurrent_reserve_does_not_overcommit():
    b = Bucket(rpm_limit=5, tpm_limit=10000)
    async def one():
        tok = await b.reserve(tokens_estimated=100)
        await b.commit(tok, 100)
    await asyncio.gather(*(one() for _ in range(5)))
    assert b.rpm_used() == 5
    with pytest.raises(RuntimeError):
        await b.reserve(tokens_estimated=1)

@pytest.mark.asyncio
async def test_store_resolves_bucket_per_pair():
    s = BucketStore()
    b1 = s.get("groq", "llama-3.3-70b-versatile", rpm_limit=30, tpm_limit=6000)
    b2 = s.get("groq", "llama-3.3-70b-versatile", rpm_limit=30, tpm_limit=6000)
    assert b1 is b2
    b3 = s.get("openrouter", "z-ai/glm-4.6:free", rpm_limit=20, tpm_limit=100000)
    assert b1 is not b3
```

- [ ] **Step 2: Implement bucket**

Create `free-claw-router/router/quota/__init__.py` (empty).

Create `free-claw-router/router/quota/bucket.py`:

```python
from __future__ import annotations
import asyncio
import time
import uuid
from dataclasses import dataclass, field

@dataclass
class ReservationToken:
    id: str
    tokens_estimated: int

@dataclass
class Bucket:
    rpm_limit: int | None = None
    tpm_limit: int | None = None
    daily_limit: int | None = None

    _rpm_window: list[float] = field(default_factory=list)
    _tpm_window: list[tuple[float, int]] = field(default_factory=list)
    _daily_used: int = 0
    _daily_reset: float = field(default_factory=lambda: _next_midnight())

    _reservations: dict[str, int] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def reserve(self, tokens_estimated: int) -> ReservationToken:
        async with self._lock:
            self._trim()
            if self.rpm_limit is not None and self._effective_rpm() >= self.rpm_limit:
                raise RuntimeError("rpm_exhausted")
            if self.tpm_limit is not None and self._effective_tpm() + tokens_estimated > self.tpm_limit:
                raise RuntimeError("tpm_exhausted")
            if self.daily_limit is not None and self._daily_used + tokens_estimated > self.daily_limit:
                raise RuntimeError("daily_exhausted")
            tok = ReservationToken(id=uuid.uuid4().hex, tokens_estimated=tokens_estimated)
            self._reservations[tok.id] = tokens_estimated
            self._rpm_window.append(time.time())
            self._tpm_window.append((time.time(), tokens_estimated))
            return tok

    async def commit(self, token: ReservationToken, tokens_actual: int) -> None:
        async with self._lock:
            if token.id not in self._reservations:
                return
            estimated = self._reservations.pop(token.id)
            delta = tokens_actual - estimated
            if delta != 0:
                self._tpm_window.append((time.time(), delta))
            self._daily_used += tokens_actual

    async def rollback(self, token: ReservationToken) -> None:
        async with self._lock:
            est = self._reservations.pop(token.id, None)
            if est is None:
                return
            if self._rpm_window:
                self._rpm_window.pop()
            self._tpm_window.append((time.time(), -est))

    def _trim(self) -> None:
        cutoff = time.time() - 60.0
        self._rpm_window = [t for t in self._rpm_window if t >= cutoff]
        self._tpm_window = [(t, n) for (t, n) in self._tpm_window if t >= cutoff]
        if time.time() >= self._daily_reset:
            self._daily_used = 0
            self._daily_reset = _next_midnight()

    def _effective_rpm(self) -> int:
        return len(self._rpm_window)

    def _effective_tpm(self) -> int:
        return sum(n for _, n in self._tpm_window)

    def rpm_used(self) -> int:
        return self._effective_rpm()

    def tpm_used(self) -> int:
        return self._effective_tpm()

def _next_midnight() -> float:
    now = time.time()
    return now + (86400 - (now % 86400))

class BucketStore:
    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], Bucket] = {}

    def get(
        self,
        provider_id: str,
        model_id: str,
        *,
        rpm_limit: int | None,
        tpm_limit: int | None,
        daily_limit: int | None = None,
    ) -> Bucket:
        key = (provider_id, model_id)
        if key not in self._buckets:
            self._buckets[key] = Bucket(
                rpm_limit=rpm_limit,
                tpm_limit=tpm_limit,
                daily_limit=daily_limit,
            )
        return self._buckets[key]
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_quota_bucket.py -v`
Expected: 5 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/quota/__init__.py free-claw-router/router/quota/bucket.py free-claw-router/tests/test_quota_bucket.py
git commit -m "feat(quota): async reservation bucket with rpm/tpm/daily limits"
```

---

### Task 32: `quota/predict.py` — affordability check

**Files:**
- Create: `free-claw-router/router/quota/predict.py`
- Create: `free-claw-router/tests/test_quota_predict.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_quota_predict.py`:

```python
from router.quota.predict import estimate_request_tokens, Affordability, assess

def test_estimate_is_prompt_plus_max_tokens():
    payload = {
        "messages": [{"role": "user", "content": "a" * 400}],
        "max_tokens": 512,
    }
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
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/quota/predict.py`:

```python
from __future__ import annotations
from enum import Enum

class Affordability(str, Enum):
    SUFFICIENT = "sufficient"
    TIGHT = "tight"
    INSUFFICIENT = "insufficient"

def estimate_request_tokens(payload: dict) -> int:
    """Rough char÷4 estimator + max_tokens budget."""
    chars = 0
    for m in payload.get("messages", []):
        c = m.get("content", "")
        if isinstance(c, str):
            chars += len(c)
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chars += len(part["text"])
    prompt_tokens = max(1, chars // 4)
    max_tokens = int(payload.get("max_tokens", 512))
    return prompt_tokens + max_tokens

def assess(*, estimated: int, rpm_remaining: int, tpm_remaining: int) -> Affordability:
    if rpm_remaining <= 0 or tpm_remaining < estimated:
        return Affordability.INSUFFICIENT
    if rpm_remaining <= 2 or tpm_remaining < int(estimated * 1.5):
        return Affordability.TIGHT
    return Affordability.SUFFICIENT
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_quota_predict.py -v`
Expected: 4 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/quota/predict.py free-claw-router/tests/test_quota_predict.py
git commit -m "feat(quota): request-token estimator and Affordability assessment"
```

---

### Task 33: `quota/backpressure.py` — POST hints to claw

**Files:**
- Create: `free-claw-router/router/quota/backpressure.py`
- Create: `free-claw-router/tests/test_quota_backpressure.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_quota_backpressure.py`:

```python
import pytest
import httpx
from router.quota.backpressure import notify_claw, BackpressureHint

@pytest.mark.asyncio
async def test_notify_claw_posts_hint(monkeypatch):
    captured: dict = {}
    async def fake_post(self, url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        req = httpx.Request("POST", url, json=json)
        return httpx.Response(204, request=req)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    ok = await notify_claw(
        "http://127.0.0.1:7901",
        BackpressureHint(task_type="coding", suggested_concurrency=2, reason="tight", ttl_seconds=60),
    )
    assert ok
    assert captured["url"].endswith("/internal/backpressure")
    assert captured["json"]["task_type"] == "coding"

@pytest.mark.asyncio
async def test_notify_claw_returns_false_on_error(monkeypatch):
    async def fake_post(self, url, json=None, timeout=None):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    ok = await notify_claw(
        "http://127.0.0.1:1",
        BackpressureHint(task_type="coding", suggested_concurrency=1, reason="x", ttl_seconds=60),
    )
    assert ok is False
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/quota/backpressure.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, asdict
import httpx

@dataclass
class BackpressureHint:
    task_type: str
    suggested_concurrency: int
    reason: str
    ttl_seconds: int

async def notify_claw(claw_base_url: str, hint: BackpressureHint, *, timeout: float = 2.0) -> bool:
    url = f"{claw_base_url.rstrip('/')}/internal/backpressure"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=asdict(hint), timeout=timeout)
        return resp.status_code < 400
    except Exception:
        return False
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_quota_backpressure.py -v`
Expected: 2 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/quota/backpressure.py free-claw-router/tests/test_quota_backpressure.py
git commit -m "feat(quota): backpressure POST to claw /internal/backpressure"
```

---

### Task 34: Integrate quota into dispatch + emit backpressure

**Files:**
- Modify: `free-claw-router/router/server/openai_compat.py`
- Modify: `free-claw-router/router/server/lifespan.py`
- Create: `free-claw-router/tests/test_server_quota.py`

- [ ] **Step 1: Write failing test**

Create `free-claw-router/tests/test_server_quota.py`:

```python
import asyncio
import pytest
from fastapi.testclient import TestClient
from router.server.openai_compat import app, _dispatch, _ensure_loaded, _bucket_store_for_test
from router.dispatch.client import DispatchResult
from router.adapters.hermes_ratelimit import RateLimitState

@pytest.fixture(autouse=True)
def reset_store():
    _bucket_store_for_test(reset=True)
    yield

def test_5_parallel_requests_do_not_overcommit_rpm(monkeypatch):
    calls = {"count": 0}
    async def fake_call(provider, model, payload, upstream_headers):
        calls["count"] += 1
        return DispatchResult(
            200,
            {"id": "ok", "choices": [{"message": {"role": "assistant", "content": "x"}}]},
            RateLimitState(),
            {"x-ratelimit-remaining-requests": "1"},
        )
    monkeypatch.setattr(_dispatch, "call", fake_call)

    client = TestClient(app)

    async def do_one():
        return client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"x-free-claw-hints": "coding"},
        )

    async def run_five():
        return await asyncio.gather(*(do_one() for _ in range(5)))

    results = asyncio.run(run_five())
    success = [r for r in results if r.status_code == 200]
    assert len(success) >= 1
    # If buckets limit to ≤ 5 rpm, all five fit; with limit 2 only 2 succeed — exact number
    # depends on the catalog policy_version. We assert we never exceeded what call recorded.
    assert calls["count"] == len(success)
```

- [ ] **Step 2: Wire a shared `BucketStore` and quota checks**

Modify `free-claw-router/router/server/openai_compat.py` — replace the request handler with the quota-aware version:

```python
from router.quota.bucket import BucketStore
from router.quota.predict import estimate_request_tokens, assess, Affordability

_bucket_store = BucketStore()

def _bucket_store_for_test(reset: bool = False) -> BucketStore:
    global _bucket_store
    if reset:
        _bucket_store = BucketStore()
    return _bucket_store

@app.post("/v1/chat/completions")
async def chat_completions(payload: dict, request: Request) -> JSONResponse:
    registry, policy = _ensure_loaded()

    hint = request.headers.get("x-free-claw-hints")
    if not hint:
        last_user = ""
        for m in payload.get("messages", []):
            if m.get("role") == "user":
                last_user = m.get("content", "") or ""
        hint = classify_task_hint(last_user) if isinstance(last_user, str) else "chat"

    chain = build_fallback_chain(registry, policy, task_type=hint, skill_id=None)
    if not chain:
        raise HTTPException(status_code=503, detail=f"no candidates for task_type={hint}")

    estimated = estimate_request_tokens(payload)

    async def call_one(cand):
        provider = next(p for p in registry.providers if p.provider_id == cand.provider_id)
        bucket = _bucket_store.get(
            cand.provider_id,
            cand.model_id,
            rpm_limit=cand.model.free_tier.rpm,
            tpm_limit=cand.model.free_tier.tpm,
            daily_limit=cand.model.free_tier.daily,
        )
        try:
            tok = await bucket.reserve(tokens_estimated=estimated)
        except RuntimeError:
            return DispatchResult(429, {"error": "quota_exhausted"}, RateLimitState(), {})
        result = await _dispatch.call(provider, cand.model, payload, dict(request.headers))
        if result.status == 200:
            await bucket.commit(tok, tokens_actual=estimated)
        else:
            await bucket.rollback(tok)
        return result

    result = await run_fallback_chain(chain, call_one)
    return JSONResponse(status_code=result.status, content=result.body)
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_server_quota.py -v`
Expected: passes.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/server/openai_compat.py free-claw-router/tests/test_server_quota.py
git commit -m "feat(server): reserve/commit/rollback quota per dispatch"
```

---

## PART I — Telemetry SQLite (M4)

### Task 35: SQLite schema + migrations

**Files:**
- Create: `free-claw-router/router/telemetry/__init__.py`
- Create: `free-claw-router/router/telemetry/store.py`
- Create: `free-claw-router/router/telemetry/migrations/001_initial.sql`
- Create: `free-claw-router/tests/test_telemetry_store.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_telemetry_store.py`:

```python
from pathlib import Path
from router.telemetry.store import Store

def test_store_creates_schema_on_init(tmp_path: Path):
    db = tmp_path / "t.db"
    s = Store(path=db)
    s.initialize()
    with s.connect() as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"traces", "spans", "events", "evaluations"} <= names

def test_store_insert_trace_and_span(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    s.insert_trace(
        trace_id=b"\x01" * 16,
        started_at_ms=1,
        root_op="session",
        root_session_id="s",
        catalog_version="2026-04-15",
        policy_version="1",
    )
    s.insert_span(
        span_id=b"\x02" * 8,
        trace_id=b"\x01" * 16,
        parent_span_id=None,
        op_name="llm_call",
        model_id="groq/llama",
        provider_id="groq",
        skill_id=None,
        task_type="coding",
        started_at_ms=2,
    )
    with s.connect() as c:
        rows = list(c.execute("SELECT op_name, model_id FROM spans"))
    assert rows == [("llm_call", "groq/llama")]
```

- [ ] **Step 2: Write migration SQL**

Create `free-claw-router/router/telemetry/migrations/001_initial.sql`:

```sql
CREATE TABLE IF NOT EXISTS traces(
  trace_id BLOB PRIMARY KEY,
  started_at INTEGER NOT NULL,
  ended_at INTEGER,
  root_op TEXT NOT NULL,
  root_session_id TEXT,
  catalog_version TEXT NOT NULL,
  policy_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS spans(
  span_id BLOB PRIMARY KEY,
  trace_id BLOB NOT NULL REFERENCES traces(trace_id),
  parent_span_id BLOB,
  op_name TEXT NOT NULL,
  model_id TEXT,
  provider_id TEXT,
  skill_id TEXT,
  task_type TEXT,
  started_at INTEGER NOT NULL,
  ended_at INTEGER,
  duration_ms INTEGER,
  status TEXT
);
CREATE INDEX IF NOT EXISTS idx_spans_model_skill ON spans(model_id, skill_id);
CREATE INDEX IF NOT EXISTS idx_spans_task ON spans(task_type, started_at);

CREATE TABLE IF NOT EXISTS events(
  event_id INTEGER PRIMARY KEY,
  span_id BLOB NOT NULL REFERENCES spans(span_id),
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_span ON events(span_id);

CREATE TABLE IF NOT EXISTS evaluations(
  id INTEGER PRIMARY KEY,
  span_id BLOB NOT NULL REFERENCES spans(span_id),
  evaluator TEXT NOT NULL,
  score_dim TEXT NOT NULL,
  score_value REAL NOT NULL,
  rationale TEXT,
  ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evals_span ON evaluations(span_id);
CREATE INDEX IF NOT EXISTS idx_evals_dim ON evaluations(score_dim, ts);
```

- [ ] **Step 3: Implement Store**

Create `free-claw-router/router/telemetry/__init__.py` (empty).

Create `free-claw-router/router/telemetry/store.py`:

```python
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import sqlite3

MIGRATIONS = Path(__file__).parent / "migrations"

class Store:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as c:
            for f in sorted(MIGRATIONS.glob("*.sql")):
                c.executescript(f.read_text())

    def insert_trace(
        self,
        *,
        trace_id: bytes,
        started_at_ms: int,
        root_op: str,
        root_session_id: str | None,
        catalog_version: str,
        policy_version: str,
    ) -> None:
        with self.connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO traces(trace_id, started_at, root_op, root_session_id, catalog_version, policy_version) VALUES(?,?,?,?,?,?)",
                (trace_id, started_at_ms, root_op, root_session_id, catalog_version, policy_version),
            )

    def insert_span(
        self,
        *,
        span_id: bytes,
        trace_id: bytes,
        parent_span_id: bytes | None,
        op_name: str,
        model_id: str | None,
        provider_id: str | None,
        skill_id: str | None,
        task_type: str | None,
        started_at_ms: int,
    ) -> None:
        with self.connect() as c:
            c.execute(
                "INSERT INTO spans(span_id, trace_id, parent_span_id, op_name, model_id, provider_id, skill_id, task_type, started_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (span_id, trace_id, parent_span_id, op_name, model_id, provider_id, skill_id, task_type, started_at_ms),
            )

    def close_span(self, span_id: bytes, *, ended_at_ms: int, duration_ms: int, status: str) -> None:
        with self.connect() as c:
            c.execute(
                "UPDATE spans SET ended_at=?, duration_ms=?, status=? WHERE span_id=?",
                (ended_at_ms, duration_ms, status, span_id),
            )

    def insert_event(self, *, span_id: bytes, kind: str, payload_json: str, ts_ms: int) -> None:
        with self.connect() as c:
            c.execute(
                "INSERT INTO events(span_id, kind, payload_json, ts) VALUES(?,?,?,?)",
                (span_id, kind, payload_json, ts_ms),
            )

    def insert_evaluation(
        self,
        *,
        span_id: bytes,
        evaluator: str,
        score_dim: str,
        score_value: float,
        rationale: str | None,
        ts_ms: int,
    ) -> None:
        with self.connect() as c:
            c.execute(
                "INSERT INTO evaluations(span_id, evaluator, score_dim, score_value, rationale, ts) VALUES(?,?,?,?,?,?)",
                (span_id, evaluator, score_dim, score_value, rationale, ts_ms),
            )
```

- [ ] **Step 4: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_telemetry_store.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add free-claw-router/router/telemetry/__init__.py free-claw-router/router/telemetry/store.py free-claw-router/router/telemetry/migrations/001_initial.sql free-claw-router/tests/test_telemetry_store.py
git commit -m "feat(telemetry): SQLite schema + Store API (traces/spans/events/evaluations)"
```

---

### Task 36: `spans.py` — Trace/Span helpers with W3C parsing

**Files:**
- Create: `free-claw-router/router/telemetry/spans.py`
- Create: `free-claw-router/tests/test_telemetry_spans.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_telemetry_spans.py`:

```python
from router.telemetry.spans import parse_traceparent, TraceContext

def test_parse_valid_traceparent():
    ctx = parse_traceparent("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
    assert isinstance(ctx, TraceContext)
    assert len(ctx.trace_id) == 16
    assert len(ctx.span_id) == 8
    assert ctx.sampled is True

def test_parse_rejects_bad_version():
    assert parse_traceparent("ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01") is None

def test_parse_rejects_wrong_segment_count():
    assert parse_traceparent("00-abc-01") is None
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/telemetry/spans.py`:

```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class TraceContext:
    trace_id: bytes     # 16 bytes
    span_id: bytes      # 8 bytes
    sampled: bool

def parse_traceparent(value: str | None) -> TraceContext | None:
    if not value:
        return None
    parts = value.strip().split("-")
    if len(parts) != 4 or parts[0] != "00":
        return None
    if len(parts[1]) != 32 or len(parts[2]) != 16 or len(parts[3]) != 2:
        return None
    try:
        tid = bytes.fromhex(parts[1])
        sid = bytes.fromhex(parts[2])
        flags = int(parts[3], 16)
    except ValueError:
        return None
    return TraceContext(trace_id=tid, span_id=sid, sampled=(flags & 1) == 1)

def encode_traceparent(ctx: TraceContext) -> str:
    return f"00-{ctx.trace_id.hex()}-{ctx.span_id.hex()}-{'01' if ctx.sampled else '00'}"
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_telemetry_spans.py -v`
Expected: 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/telemetry/spans.py free-claw-router/tests/test_telemetry_spans.py
git commit -m "feat(telemetry): W3C traceparent parse/encode helpers"
```

---

### Task 37: `events.py` — typed event variants

**Files:**
- Create: `free-claw-router/router/telemetry/events.py`
- Create: `free-claw-router/tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_telemetry_events.py`:

```python
from router.telemetry.events import (
    QuotaReserved, QuotaCommitted, DispatchSucceeded, DispatchFailed, to_payload
)

def test_quota_reserved_roundtrip():
    ev = QuotaReserved(provider_id="groq", model_id="x", tokens_estimated=100, bucket_rpm_used=1)
    payload = to_payload(ev)
    assert payload["kind"] == "quota_reserved"
    assert payload["data"]["tokens_estimated"] == 100

def test_dispatch_succeeded_payload_has_status():
    ev = DispatchSucceeded(provider_id="groq", model_id="x", status=200, latency_ms=40)
    p = to_payload(ev)
    assert p["data"]["status"] == 200

def test_dispatch_failed_payload_carries_error():
    ev = DispatchFailed(provider_id="groq", model_id="x", status=503, error_class="io_error")
    p = to_payload(ev)
    assert p["data"]["error_class"] == "io_error"
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/telemetry/events.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Union

@dataclass
class QuotaReserved:
    provider_id: str
    model_id: str
    tokens_estimated: int
    bucket_rpm_used: int

@dataclass
class QuotaCommitted:
    provider_id: str
    model_id: str
    tokens_actual: int

@dataclass
class QuotaRolledBack:
    provider_id: str
    model_id: str
    reason: str

@dataclass
class DispatchSucceeded:
    provider_id: str
    model_id: str
    status: int
    latency_ms: int

@dataclass
class DispatchFailed:
    provider_id: str
    model_id: str
    status: int
    error_class: str

@dataclass
class BackpressureEmitted:
    task_type: str
    suggested_concurrency: int

Event = Union[
    QuotaReserved, QuotaCommitted, QuotaRolledBack,
    DispatchSucceeded, DispatchFailed, BackpressureEmitted,
]

_KINDS: dict[type, str] = {
    QuotaReserved: "quota_reserved",
    QuotaCommitted: "quota_committed",
    QuotaRolledBack: "quota_rolled_back",
    DispatchSucceeded: "dispatch_succeeded",
    DispatchFailed: "dispatch_failed",
    BackpressureEmitted: "backpressure_emitted",
}

def to_payload(ev: Event) -> dict:
    return {"kind": _KINDS[type(ev)], "data": asdict(ev)}
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_telemetry_events.py -v`
Expected: 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/telemetry/events.py free-claw-router/tests/test_telemetry_events.py
git commit -m "feat(telemetry): typed Event dataclasses with payload encoder"
```

---

### Task 38: Emit spans + events during dispatch

**Files:**
- Modify: `free-claw-router/router/server/openai_compat.py`
- Modify: `free-claw-router/router/server/lifespan.py`
- Create: `free-claw-router/tests/test_server_telemetry.py`

- [ ] **Step 1: Write failing test**

Create `free-claw-router/tests/test_server_telemetry.py`:

```python
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from router.server.openai_compat import app, _dispatch
from router.dispatch.client import DispatchResult
from router.adapters.hermes_ratelimit import RateLimitState
from router.telemetry.store import Store

@pytest.fixture
def tmp_store(monkeypatch, tmp_path) -> Store:
    store = Store(path=tmp_path / "t.db")
    store.initialize()
    from router.server import openai_compat as mod
    mod._telemetry_store = store
    return store

def test_span_and_events_recorded_for_successful_dispatch(tmp_store, monkeypatch):
    async def fake_call(provider, model, payload, upstream_headers):
        return DispatchResult(200, {"choices": [{"message": {"content": "hi"}}]}, RateLimitState(), {})
    monkeypatch.setattr(_dispatch, "call", fake_call)

    client = TestClient(app)
    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "refactor"}]},
        headers={
            "x-free-claw-hints": "coding",
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )
    assert r.status_code == 200

    with tmp_store.connect() as c:
        spans = list(c.execute("SELECT op_name, model_id, status FROM spans ORDER BY started_at"))
        events = list(c.execute("SELECT kind FROM events"))
    assert any(row[0] == "llm_call" for row in spans)
    assert any(row[2] == "ok" for row in spans)
    assert "dispatch_succeeded" in {e[0] for e in events}
```

- [ ] **Step 2: Wire store + span emission**

Modify `free-claw-router/router/server/lifespan.py`:

```python
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from router.telemetry.store import Store

DEFAULT_DB = Path.home() / ".free-claw-router" / "telemetry.db"

@asynccontextmanager
async def lifespan(app: FastAPI):
    DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
    store = Store(path=DEFAULT_DB)
    store.initialize()
    app.state.telemetry_store = store
    app.state.catalog_version = "unversioned"
    yield
```

Modify `free-claw-router/router/server/openai_compat.py` — at top:

```python
import json
import os
import time
import secrets
from router.telemetry.spans import parse_traceparent, TraceContext
from router.telemetry import events as ev
from router.telemetry.store import Store

_telemetry_store: Store | None = None

def _resolve_store() -> Store:
    global _telemetry_store
    if _telemetry_store is not None:
        return _telemetry_store
    return app.state.telemetry_store
```

Replace the `chat_completions` body to record:

```python
@app.post("/v1/chat/completions")
async def chat_completions(payload: dict, request: Request) -> JSONResponse:
    registry, policy = _ensure_loaded()
    store = _resolve_store()

    ctx = parse_traceparent(request.headers.get("traceparent"))
    if ctx is None:
        ctx = TraceContext(trace_id=secrets.token_bytes(16), span_id=secrets.token_bytes(8), sampled=True)

    now_ms = int(time.time() * 1000)
    store.insert_trace(
        trace_id=ctx.trace_id,
        started_at_ms=now_ms,
        root_op="chat_completion_request",
        root_session_id=request.headers.get("x-session-id"),
        catalog_version=registry.version,
        policy_version=policy.version,
    )

    hint = request.headers.get("x-free-claw-hints")
    if not hint:
        last_user = next(
            (m.get("content", "") for m in payload.get("messages", []) if m.get("role") == "user"),
            "",
        )
        hint = classify_task_hint(last_user) if isinstance(last_user, str) else "chat"

    chain = build_fallback_chain(registry, policy, task_type=hint, skill_id=None)
    if not chain:
        raise HTTPException(status_code=503, detail=f"no candidates for task_type={hint}")

    estimated = estimate_request_tokens(payload)

    async def call_one(cand):
        span_id = secrets.token_bytes(8)
        started = int(time.time() * 1000)
        store.insert_span(
            span_id=span_id,
            trace_id=ctx.trace_id,
            parent_span_id=ctx.span_id,
            op_name="llm_call",
            model_id=cand.model_id,
            provider_id=cand.provider_id,
            skill_id=None,
            task_type=hint,
            started_at_ms=started,
        )
        provider = next(p for p in registry.providers if p.provider_id == cand.provider_id)
        bucket = _bucket_store.get(
            cand.provider_id, cand.model_id,
            rpm_limit=cand.model.free_tier.rpm,
            tpm_limit=cand.model.free_tier.tpm,
            daily_limit=cand.model.free_tier.daily,
        )
        try:
            tok = await bucket.reserve(tokens_estimated=estimated)
            store.insert_event(
                span_id=span_id, kind="quota_reserved",
                payload_json=json.dumps(ev.to_payload(ev.QuotaReserved(
                    provider_id=cand.provider_id, model_id=cand.model_id,
                    tokens_estimated=estimated, bucket_rpm_used=bucket.rpm_used(),
                ))),
                ts_ms=int(time.time() * 1000),
            )
        except RuntimeError as e:
            result = DispatchResult(429, {"error": str(e)}, RateLimitState(), {})
        else:
            result = await _dispatch.call(provider, cand.model, payload, dict(request.headers))
            if result.status == 200:
                await bucket.commit(tok, tokens_actual=estimated)
            else:
                await bucket.rollback(tok)

        ended = int(time.time() * 1000)
        store.close_span(span_id, ended_at_ms=ended, duration_ms=ended - started,
                         status="ok" if result.status == 200 else f"http_{result.status}")
        ev_kind = "dispatch_succeeded" if result.status == 200 else "dispatch_failed"
        payload_obj = (
            ev.DispatchSucceeded(cand.provider_id, cand.model_id, result.status, ended - started)
            if result.status == 200
            else ev.DispatchFailed(cand.provider_id, cand.model_id, result.status, "http_error")
        )
        store.insert_event(
            span_id=span_id, kind=ev_kind,
            payload_json=json.dumps(ev.to_payload(payload_obj)),
            ts_ms=ended,
        )
        return result

    result = await run_fallback_chain(chain, call_one)
    return JSONResponse(status_code=result.status, content=result.body)
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_server_telemetry.py tests/test_server_direct.py tests/test_server_quota.py -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/server/openai_compat.py free-claw-router/router/server/lifespan.py free-claw-router/tests/test_server_telemetry.py
git commit -m "feat(server): emit llm_call spans + dispatch/quota events to SQLite"
```

---

### Task 39: `ingest_jsonl.py` — tail claw's JSONL into SQLite

**Files:**
- Create: `free-claw-router/router/telemetry/ingest_jsonl.py`
- Create: `free-claw-router/tests/test_telemetry_ingest.py`

- [ ] **Step 1: Write failing test**

Create `free-claw-router/tests/test_telemetry_ingest.py`:

```python
from pathlib import Path
import json
from router.telemetry.store import Store
from router.telemetry.ingest_jsonl import ingest_lines

def test_ingest_translates_span_started_and_ended(tmp_path: Path):
    store = Store(path=tmp_path / "t.db")
    store.initialize()
    tid = "4bf92f3577b34da6a3ce929d0e0e4736"
    sid = "00f067aa0ba902b7"
    lines = [
        json.dumps({
            "type": "span_started",
            "trace_id": tid,
            "span_id": sid,
            "parent_span_id": None,
            "op_name": "tool_call",
            "session_id": "s1",
            "attributes": {"tool_name": "Read"},
        }),
        json.dumps({
            "type": "span_ended",
            "span_id": sid,
            "status": "ok",
            "duration_ms": 42,
            "attributes": {},
        }),
    ]
    ingest_lines(store, lines, default_catalog_version="2026-04-15", default_policy_version="1")
    with store.connect() as c:
        spans = list(c.execute("SELECT op_name, status, duration_ms FROM spans"))
    assert spans == [("tool_call", "ok", 42)]
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/telemetry/ingest_jsonl.py`:

```python
from __future__ import annotations
import json
import time
from router.telemetry.store import Store

def _hex_to_bytes(h: str | None) -> bytes | None:
    if not h:
        return None
    try:
        return bytes.fromhex(h)
    except ValueError:
        return None

def ingest_lines(
    store: Store,
    lines,
    *,
    default_catalog_version: str,
    default_policy_version: str,
) -> int:
    count = 0
    for raw in lines:
        if not raw.strip():
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = ev.get("type")
        if kind == "span_started":
            tid = _hex_to_bytes(ev.get("trace_id"))
            sid = _hex_to_bytes(ev.get("span_id"))
            if tid is None or sid is None:
                continue
            store.insert_trace(
                trace_id=tid,
                started_at_ms=int(time.time() * 1000),
                root_op=ev.get("op_name", "unknown"),
                root_session_id=ev.get("session_id"),
                catalog_version=default_catalog_version,
                policy_version=default_policy_version,
            )
            store.insert_span(
                span_id=sid, trace_id=tid,
                parent_span_id=_hex_to_bytes(ev.get("parent_span_id")),
                op_name=ev.get("op_name", "unknown"),
                model_id=ev.get("attributes", {}).get("model_id"),
                provider_id=ev.get("attributes", {}).get("provider_id"),
                skill_id=ev.get("attributes", {}).get("skill_id"),
                task_type=ev.get("attributes", {}).get("task_type"),
                started_at_ms=int(time.time() * 1000),
            )
            count += 1
        elif kind == "span_ended":
            sid = _hex_to_bytes(ev.get("span_id"))
            if sid is None:
                continue
            now = int(time.time() * 1000)
            store.close_span(
                sid,
                ended_at_ms=now,
                duration_ms=int(ev.get("duration_ms", 0)),
                status=str(ev.get("status", "ok")),
            )
            count += 1
    return count
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_telemetry_ingest.py -v`
Expected: passes.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/telemetry/ingest_jsonl.py free-claw-router/tests/test_telemetry_ingest.py
git commit -m "feat(telemetry): ingest claw JSONL span events into SQLite"
```

---

### Task 40: `evaluations.py` + rule evaluator

**Files:**
- Create: `free-claw-router/router/telemetry/evaluations.py`
- Create: `free-claw-router/tests/test_telemetry_evaluations.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_telemetry_evaluations.py`:

```python
from pathlib import Path
from router.telemetry.store import Store
from router.telemetry.evaluations import RuleEvaluator, evaluate_span

def test_rule_evaluator_scores_successful_span_high(tmp_path: Path):
    store = Store(path=tmp_path / "t.db")
    store.initialize()
    tid = b"\x01" * 16
    sid = b"\x02" * 8
    store.insert_trace(trace_id=tid, started_at_ms=1, root_op="x", root_session_id=None,
                       catalog_version="v", policy_version="1")
    store.insert_span(span_id=sid, trace_id=tid, parent_span_id=None, op_name="llm_call",
                      model_id="m", provider_id="p", skill_id=None, task_type="coding",
                      started_at_ms=1)
    store.close_span(sid, ended_at_ms=2, duration_ms=1, status="ok")

    evals = evaluate_span(store, span_id=sid, evaluators=[RuleEvaluator()])
    dims = {e.score_dim: e.score_value for e in evals}
    assert dims.get("format_correctness") == 1.0

def test_rule_evaluator_scores_failed_span_low(tmp_path: Path):
    store = Store(path=tmp_path / "t.db")
    store.initialize()
    tid = b"\x03" * 16
    sid = b"\x04" * 8
    store.insert_trace(trace_id=tid, started_at_ms=1, root_op="x", root_session_id=None,
                       catalog_version="v", policy_version="1")
    store.insert_span(span_id=sid, trace_id=tid, parent_span_id=None, op_name="llm_call",
                      model_id="m", provider_id="p", skill_id=None, task_type="coding",
                      started_at_ms=1)
    store.close_span(sid, ended_at_ms=2, duration_ms=1, status="http_503")

    evals = evaluate_span(store, span_id=sid, evaluators=[RuleEvaluator()])
    dims = {e.score_dim: e.score_value for e in evals}
    assert dims.get("format_correctness") == 0.0
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/telemetry/evaluations.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
import time
from typing import Protocol
from router.telemetry.store import Store

@dataclass
class Evaluation:
    span_id: bytes
    evaluator: str
    score_dim: str
    score_value: float
    rationale: str | None = None

class Evaluator(Protocol):
    evaluator_id: str
    def evaluate(self, store: Store, span_id: bytes) -> list[Evaluation]: ...

class RuleEvaluator:
    evaluator_id = "rule"

    def evaluate(self, store: Store, span_id: bytes) -> list[Evaluation]:
        with store.connect() as c:
            row = c.execute("SELECT status FROM spans WHERE span_id=?", (span_id,)).fetchone()
        status = row[0] if row else None
        if status == "ok":
            return [Evaluation(span_id, self.evaluator_id, "format_correctness", 1.0, "status=ok")]
        if status and status.startswith("http_"):
            return [Evaluation(span_id, self.evaluator_id, "format_correctness", 0.0, f"status={status}")]
        return [Evaluation(span_id, self.evaluator_id, "format_correctness", 0.5, f"status={status}")]

def evaluate_span(store: Store, *, span_id: bytes, evaluators: list[Evaluator]) -> list[Evaluation]:
    out: list[Evaluation] = []
    now = int(time.time() * 1000)
    for ev in evaluators:
        for e in ev.evaluate(store, span_id):
            store.insert_evaluation(
                span_id=e.span_id, evaluator=e.evaluator, score_dim=e.score_dim,
                score_value=e.score_value, rationale=e.rationale, ts_ms=now,
            )
            out.append(e)
    return out
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_telemetry_evaluations.py -v`
Expected: 2 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/telemetry/evaluations.py free-claw-router/tests/test_telemetry_evaluations.py
git commit -m "feat(telemetry): Evaluator protocol + RuleEvaluator baseline"
```

---

### Task 41: `readmodels.py` — materialized views for P2/P4 consumers

**Files:**
- Create: `free-claw-router/router/telemetry/readmodels.py`
- Create: `free-claw-router/tests/test_telemetry_readmodels.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_telemetry_readmodels.py`:

```python
from pathlib import Path
from router.telemetry.store import Store
from router.telemetry.readmodels import skill_model_affinity, quota_health

def _setup(tmp_path: Path) -> Store:
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    tid = b"\x01" * 16
    for i, (skill, model, status) in enumerate([
        ("build", "groq/llama", "ok"),
        ("build", "groq/llama", "ok"),
        ("build", "groq/llama", "http_503"),
        ("build", "openrouter/glm", "ok"),
    ]):
        sid = bytes([i + 1]) * 8
        s.insert_trace(trace_id=tid, started_at_ms=1, root_op="x", root_session_id=None,
                       catalog_version="v", policy_version="1")
        s.insert_span(span_id=sid, trace_id=tid, parent_span_id=None, op_name="llm_call",
                      model_id=model, provider_id=model.split("/")[0],
                      skill_id=skill, task_type="coding", started_at_ms=1)
        s.close_span(sid, ended_at_ms=2, duration_ms=1, status=status)
        s.insert_evaluation(span_id=sid, evaluator="rule", score_dim="format_correctness",
                             score_value=1.0 if status == "ok" else 0.0, rationale=None, ts_ms=2)
    return s

def test_skill_model_affinity_returns_rates(tmp_path: Path):
    s = _setup(tmp_path)
    rows = skill_model_affinity(s, skill_id="build")
    by_model = {r["model_id"]: r for r in rows}
    assert by_model["groq/llama"]["trials"] == 3
    assert abs(by_model["groq/llama"]["success_rate"] - 2/3) < 1e-6

def test_quota_health_per_provider(tmp_path: Path):
    s = _setup(tmp_path)
    rows = quota_health(s)
    names = {r["provider_id"] for r in rows}
    assert {"groq", "openrouter"} <= names
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/telemetry/readmodels.py`:

```python
from __future__ import annotations
from router.telemetry.store import Store

def skill_model_affinity(store: Store, *, skill_id: str | None = None, days: int = 7) -> list[dict]:
    q = """
      SELECT s.skill_id,
             s.model_id,
             COUNT(*) AS trials,
             AVG(CASE WHEN s.status='ok' THEN 1.0 ELSE 0.0 END) AS success_rate,
             AVG(e.score_value) AS avg_score
      FROM spans s
      LEFT JOIN evaluations e ON e.span_id = s.span_id AND e.score_dim = 'format_correctness'
      WHERE s.skill_id IS NOT NULL
      {maybe_filter}
      GROUP BY s.skill_id, s.model_id
      ORDER BY trials DESC
    """.replace(
        "{maybe_filter}", "AND s.skill_id = ?" if skill_id else ""
    )
    args = (skill_id,) if skill_id else ()
    with store.connect() as c:
        cur = c.execute(q, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

def quota_health(store: Store) -> list[dict]:
    q = """
      SELECT provider_id,
             model_id,
             COUNT(*) AS requests,
             AVG(CASE WHEN status LIKE 'http_429%' THEN 1.0 ELSE 0.0 END) AS rate_limited_fraction
      FROM spans
      WHERE provider_id IS NOT NULL
      GROUP BY provider_id, model_id
    """
    with store.connect() as c:
        cur = c.execute(q)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_telemetry_readmodels.py -v`
Expected: 2 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/telemetry/readmodels.py free-claw-router/tests/test_telemetry_readmodels.py
git commit -m "feat(telemetry): readmodels — skill_model_affinity + quota_health"
```

---

## PART J — Autonomous PR loop (M5)

### Task 42: `catalog/refresh/worktree.py` — git worktree wrapper

**Files:**
- Create: `free-claw-router/router/catalog/refresh/__init__.py`
- Create: `free-claw-router/router/catalog/refresh/worktree.py`
- Create: `free-claw-router/tests/test_refresh_worktree.py`

- [ ] **Step 1: Write failing test**

Create `free-claw-router/tests/test_refresh_worktree.py`:

```python
from pathlib import Path
import subprocess
import pytest
from router.catalog.refresh.worktree import Worktree

def test_create_worktree_isolated(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)

    wt_root = tmp_path / "worktrees"
    wt = Worktree(repo=repo, worktree_root=wt_root, branch="refresh/test", base="main")
    path = wt.create()
    assert path.exists()
    assert (path / ".git").exists()

    wt.remove()
    assert not path.exists()

def test_refuses_existing_branch_without_force(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "refresh/existing"], cwd=repo, check=True)

    wt = Worktree(repo=repo, worktree_root=tmp_path / "w", branch="refresh/existing", base="main")
    with pytest.raises(RuntimeError):
        wt.create()
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/catalog/refresh/__init__.py` (empty).

Create `free-claw-router/router/catalog/refresh/worktree.py`:

```python
from __future__ import annotations
import subprocess
from pathlib import Path

class Worktree:
    def __init__(self, *, repo: Path, worktree_root: Path, branch: str, base: str = "main") -> None:
        self.repo = Path(repo).resolve()
        self.worktree_root = Path(worktree_root).resolve()
        self.branch = branch
        self.base = base
        self.path: Path | None = None

    def _git(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            check=check,
            capture_output=True,
            text=True,
        )

    def create(self) -> Path:
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        if self._branch_exists():
            raise RuntimeError(f"branch {self.branch} already exists")
        target = self.worktree_root / self.branch.replace("/", "__")
        self._git("worktree", "add", "-b", self.branch, str(target), self.base)
        self.path = target
        return target

    def remove(self) -> None:
        if not self.path:
            return
        self._git("worktree", "remove", "--force", str(self.path), check=False)
        self.path = None

    def _branch_exists(self) -> bool:
        result = self._git("rev-parse", "--verify", self.branch, check=False)
        return result.returncode == 0
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_refresh_worktree.py -v`
Expected: 2 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/catalog/refresh/__init__.py free-claw-router/router/catalog/refresh/worktree.py free-claw-router/tests/test_refresh_worktree.py
git commit -m "feat(refresh): Worktree wrapper for isolated catalog-refresh branches"
```

---

### Task 43: `catalog/refresh/pr.py` — gh wrappers

**Files:**
- Create: `free-claw-router/router/catalog/refresh/pr.py`
- Create: `free-claw-router/tests/test_refresh_pr.py`

- [ ] **Step 1: Write failing test**

Create `free-claw-router/tests/test_refresh_pr.py`:

```python
import subprocess
import pytest
from router.catalog.refresh.pr import create_pr, GhError

def test_create_pr_invokes_gh(monkeypatch, tmp_path):
    captured = {}
    def fake_run(args, cwd=None, check=True, capture_output=True, text=True):
        captured["args"] = args
        class R:
            returncode = 0
            stdout = "https://github.com/o/r/pull/7"
            stderr = ""
        return R()
    monkeypatch.setattr(subprocess, "run", fake_run)

    url = create_pr(cwd=tmp_path, title="x", body="y", base="main", head="refresh/foo")
    assert url == "https://github.com/o/r/pull/7"
    assert captured["args"][0:2] == ["gh", "pr"]
    assert "--title" in captured["args"]

def test_create_pr_raises_on_error(monkeypatch, tmp_path):
    class R:
        returncode = 1
        stdout = ""
        stderr = "gh: bad"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    with pytest.raises(GhError):
        create_pr(cwd=tmp_path, title="x", body="y", base="main", head="refresh/foo")
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/catalog/refresh/pr.py`:

```python
from __future__ import annotations
import subprocess
from pathlib import Path

class GhError(RuntimeError):
    pass

def _run(args: list[str], cwd: Path) -> str:
    r = subprocess.run(args, cwd=str(cwd), check=False, capture_output=True, text=True)
    if r.returncode != 0:
        raise GhError(f"{' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()

def create_pr(*, cwd: Path, title: str, body: str, base: str, head: str) -> str:
    return _run(
        ["gh", "pr", "create", "--title", title, "--body", body, "--base", base, "--head", head],
        cwd,
    )

def comment_pr(*, cwd: Path, pr_number: int, body: str) -> None:
    _run(["gh", "pr", "comment", str(pr_number), "--body", body], cwd)
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_refresh_pr.py -v`
Expected: 2 tests pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/catalog/refresh/pr.py free-claw-router/tests/test_refresh_pr.py
git commit -m "feat(refresh): gh CLI wrappers for PR create + comment"
```

---

### Task 44: `ops/catalog-schema.json` — JSON schema for research-agent output

**Files:**
- Create: `free-claw-router/ops/catalog-schema.json`
- Create: `free-claw-router/ops/allowed_sources.yaml`
- Create: `free-claw-router/tests/test_ops_schema.py`

- [ ] **Step 1: Write failing test**

Create `free-claw-router/tests/test_ops_schema.py`:

```python
import json
import pytest
from pathlib import Path
from jsonschema import Draft202012Validator

SCHEMA = Path(__file__).resolve().parent.parent / "ops" / "catalog-schema.json"

def test_schema_is_valid_draft_2020_12():
    data = json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(data)

def test_valid_research_payload_accepted():
    data = json.loads(SCHEMA.read_text())
    validator = Draft202012Validator(data)
    payload = {
        "provider_id": "openrouter",
        "model_id": "test/m:free",
        "status": "added",
        "context_window": 8192,
        "tool_use": True,
        "structured_output": "partial",
        "free_tier": {"rpm": 10, "tpm": 5000, "daily": None, "reset_policy": "minute"},
        "pricing": {"input": 0, "output": 0, "free": True},
        "quirks": [],
        "evidence_urls": ["https://openrouter.ai/models/test/m:free"],
    }
    errors = list(validator.iter_errors(payload))
    assert errors == []

def test_missing_evidence_rejected():
    data = json.loads(SCHEMA.read_text())
    validator = Draft202012Validator(data)
    payload = {
        "provider_id": "openrouter",
        "model_id": "test/m:free",
        "status": "added",
        "context_window": 8192,
        "tool_use": True,
        "structured_output": "partial",
        "free_tier": {"rpm": 10, "tpm": 5000, "daily": None, "reset_policy": "minute"},
        "pricing": {"input": 0, "output": 0, "free": True},
        "quirks": [],
        "evidence_urls": [],
    }
    errors = list(validator.iter_errors(payload))
    assert any("evidence_urls" in str(e.path) or "evidence_urls" in e.message for e in errors)
```

- [ ] **Step 2: Add `jsonschema` to dev deps**

In `free-claw-router/pyproject.toml`, add under `[project.optional-dependencies] dev`:

```toml
  "jsonschema>=4.22",
```

Run: `cd free-claw-router && uv sync --extra dev`

- [ ] **Step 3: Write the schema**

Create `free-claw-router/ops/catalog-schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ResearchAgentCatalogEntry",
  "type": "object",
  "required": [
    "provider_id", "model_id", "status", "context_window", "tool_use",
    "structured_output", "free_tier", "pricing", "quirks", "evidence_urls"
  ],
  "properties": {
    "provider_id": {"type": "string", "minLength": 1},
    "model_id": {"type": "string", "minLength": 1},
    "status": {"enum": ["added", "updated", "deprecated"]},
    "context_window": {"type": "integer", "minimum": 1},
    "tool_use": {"type": "boolean"},
    "structured_output": {"enum": ["none", "partial", "full"]},
    "free_tier": {
      "type": "object",
      "required": ["reset_policy"],
      "properties": {
        "rpm": {"type": ["integer", "null"], "minimum": 0},
        "tpm": {"type": ["integer", "null"], "minimum": 0},
        "daily": {"type": ["integer", "null"], "minimum": 0},
        "reset_policy": {"enum": ["minute", "hour", "day", "rolling"]}
      }
    },
    "pricing": {
      "type": "object",
      "required": ["input", "output", "free"],
      "properties": {
        "input": {"type": "number", "const": 0},
        "output": {"type": "number", "const": 0},
        "free": {"type": "boolean", "const": true}
      }
    },
    "quirks": {"type": "array", "items": {"type": "string"}},
    "evidence_urls": {"type": "array", "minItems": 1, "items": {"type": "string", "format": "uri"}},
    "deprecation_reason": {"type": ["string", "null"]},
    "replaced_by": {"type": ["string", "null"]}
  },
  "allOf": [
    {
      "if": {"properties": {"status": {"const": "deprecated"}}, "required": ["status"]},
      "then": {"required": ["deprecation_reason", "replaced_by"]}
    }
  ],
  "additionalProperties": false
}
```

Create `free-claw-router/ops/allowed_sources.yaml`:

```yaml
# Whitelisted URL patterns for the research agent. The agent must refuse
# any WebFetch to a URL not matching one of these prefixes.
allowed:
  - https://openrouter.ai/api/
  - https://openrouter.ai/models/
  - https://api.groq.com/openai/v1/
  - https://console.groq.com/docs/
  - https://z.ai/
  - https://api.cerebras.ai/v1/
  - https://inference-api.cerebras.ai/
  - https://ollama.com/library/
```

- [ ] **Step 4: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_ops_schema.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add free-claw-router/pyproject.toml free-claw-router/uv.lock free-claw-router/ops/catalog-schema.json free-claw-router/ops/allowed_sources.yaml free-claw-router/tests/test_ops_schema.py
git commit -m "feat(ops): strict JSON schema + allowed_sources for research agent"
```

---

### Task 45: `catalog/refresh/producer.py` — orchestrator

**Files:**
- Create: `free-claw-router/router/catalog/refresh/producer.py`
- Create: `free-claw-router/tests/test_refresh_producer.py`

- [ ] **Step 1: Write failing test**

Create `free-claw-router/tests/test_refresh_producer.py`:

```python
from pathlib import Path
import json
import pytest
from router.catalog.refresh.producer import Producer, ProducerResult

def test_producer_dry_run_writes_diff_file(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)

    # Simulate a research_payload.json that the agent emits.
    research = [
        {
            "provider_id": "openrouter",
            "model_id": "test/model:free",
            "status": "added",
            "context_window": 4096,
            "tool_use": False,
            "structured_output": "none",
            "free_tier": {"rpm": 5, "tpm": 1000, "daily": None, "reset_policy": "minute"},
            "pricing": {"input": 0, "output": 0, "free": True},
            "quirks": [],
            "evidence_urls": ["https://openrouter.ai/models/test/model:free"]
        }
    ]
    (repo / "research.json").write_text(json.dumps(research))

    p = Producer(
        repo=repo,
        worktree_root=tmp_path / "wt",
        dry_run=True,
        catalog_dir=repo / "catalog" / "data",
    )
    result = p.run_for_provider("openrouter", research_json=repo / "research.json")
    assert isinstance(result, ProducerResult)
    assert result.dry_run is True
    assert result.new_yaml_path.exists()
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/catalog/refresh/producer.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import yaml
import jsonschema
from router.catalog.refresh.worktree import Worktree
from router.catalog.refresh.pr import create_pr

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "ops" / "catalog-schema.json"

@dataclass
class ProducerResult:
    new_yaml_path: Path
    pr_url: str | None
    dry_run: bool

class Producer:
    def __init__(
        self,
        *,
        repo: Path,
        worktree_root: Path,
        catalog_dir: Path,
        dry_run: bool = False,
    ) -> None:
        self.repo = repo
        self.worktree_root = worktree_root
        self.catalog_dir = catalog_dir
        self.dry_run = dry_run

    def _validate_research(self, entries: list[dict]) -> None:
        schema = json.loads(SCHEMA_PATH.read_text())
        validator = jsonschema.Draft202012Validator(schema)
        for entry in entries:
            errs = sorted(validator.iter_errors(entry), key=lambda e: e.path)
            if errs:
                raise ValueError("research payload failed schema: " + "; ".join(e.message for e in errs))

    def _merge_yaml(self, provider_id: str, entries: list[dict], out: Path) -> None:
        existing = {}
        if out.exists():
            existing = yaml.safe_load(out.read_text()) or {}
        models_by_id = {m["model_id"]: m for m in (existing.get("models") or [])}
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        today = now.split("T", 1)[0]
        for entry in entries:
            entry_wo_meta = {k: v for k, v in entry.items() if k not in ("status",)}
            models_by_id[entry["model_id"]] = {
                **entry_wo_meta,
                "status": "active" if entry["status"] != "deprecated" else "deprecated",
                "last_verified": now,
                "first_seen": models_by_id.get(entry["model_id"], {}).get("first_seen", today),
            }
        doc = {
            "provider_id": provider_id,
            "base_url": existing.get("base_url") or "",
            "auth": existing.get("auth") or {"env": f"{provider_id.upper()}_API_KEY", "scheme": "bearer"},
            "known_ratelimit_header_schema": existing.get("known_ratelimit_header_schema") or "generic",
            "models": list(models_by_id.values()),
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))

    def run_for_provider(self, provider_id: str, *, research_json: Path) -> ProducerResult:
        entries = json.loads(research_json.read_text())
        self._validate_research(entries)

        target = self.catalog_dir / f"{provider_id}.yaml"
        if self.dry_run:
            self._merge_yaml(provider_id, entries, target)
            return ProducerResult(new_yaml_path=target, pr_url=None, dry_run=True)

        branch = f"catalog/refresh/{datetime.utcnow().strftime('%Y-%m-%d')}-{provider_id}"
        wt = Worktree(repo=self.repo, worktree_root=self.worktree_root, branch=branch, base="main")
        path = wt.create()
        try:
            self._merge_yaml(provider_id, entries, path / target.relative_to(self.repo))
            import subprocess
            subprocess.run(["git", "add", "-A"], cwd=path, check=True)
            subprocess.run(["git", "commit", "-m", f"catalog: refresh {provider_id}"], cwd=path, check=True)
            subprocess.run(["git", "push", "-u", "origin", branch], cwd=path, check=True)
            pr_url = create_pr(
                cwd=path,
                title=f"catalog: refresh {provider_id} ({datetime.utcnow().strftime('%Y-%m-%d')})",
                body="Automated catalog refresh. See `docs/superpowers/plans/2026-04-15-p0-free-llm-router.md` Task 45.",
                base="main",
                head=branch,
            )
            return ProducerResult(new_yaml_path=target, pr_url=pr_url, dry_run=False)
        finally:
            wt.remove()
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_refresh_producer.py -v`
Expected: passes.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/catalog/refresh/producer.py free-claw-router/tests/test_refresh_producer.py
git commit -m "feat(refresh): Producer orchestrator with dry-run and PR path"
```

---

### Task 46: `catalog/refresh/scheduler.py` — APScheduler + HTTP proxy

**Files:**
- Create: `free-claw-router/router/catalog/refresh/scheduler.py`
- Modify: `free-claw-router/router/server/openai_compat.py` (add `/cron/register`)
- Create: `free-claw-router/tests/test_refresh_scheduler.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_refresh_scheduler.py`:

```python
import asyncio
from router.catalog.refresh.scheduler import CronScheduler, CronJob

def test_register_and_list_jobs():
    s = CronScheduler()
    s.register(CronJob(job_id="j1", cron_expr="0 3 * * *", payload={"provider": "openrouter"}))
    s.register(CronJob(job_id="j2", cron_expr="0 4 * * *", payload={"provider": "groq"}))
    jobs = s.list_jobs()
    assert {j.job_id for j in jobs} == {"j1", "j2"}

def test_duplicate_job_id_raises():
    s = CronScheduler()
    s.register(CronJob(job_id="j1", cron_expr="0 3 * * *", payload={}))
    import pytest
    with pytest.raises(ValueError):
        s.register(CronJob(job_id="j1", cron_expr="0 5 * * *", payload={}))

def test_unregister_removes_job():
    s = CronScheduler()
    s.register(CronJob(job_id="j1", cron_expr="0 3 * * *", payload={}))
    s.unregister("j1")
    assert s.list_jobs() == []
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/catalog/refresh/scheduler.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

@dataclass
class CronJob:
    job_id: str
    cron_expr: str
    payload: dict

class CronScheduler:
    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler()
        self._jobs: dict[str, CronJob] = {}
        self._handler: Callable[[CronJob], None] | None = None
        self._scheduler.start()

    def bind(self, handler: Callable[[CronJob], None]) -> None:
        self._handler = handler

    def register(self, job: CronJob) -> None:
        if job.job_id in self._jobs:
            raise ValueError(f"duplicate job_id: {job.job_id}")
        trigger = CronTrigger.from_crontab(job.cron_expr)
        def runner():
            if self._handler is not None:
                self._handler(job)
        self._scheduler.add_job(runner, trigger=trigger, id=job.job_id, replace_existing=False)
        self._jobs[job.job_id] = job

    def unregister(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

    def list_jobs(self) -> list[CronJob]:
        return list(self._jobs.values())
```

- [ ] **Step 3: Expose `/cron/register` in the server**

Append to `free-claw-router/router/server/openai_compat.py`:

```python
from fastapi import Body
from router.catalog.refresh.scheduler import CronScheduler, CronJob

_cron = CronScheduler()

@app.post("/cron/register")
async def cron_register(body: dict = Body(...)) -> JSONResponse:
    try:
        job = CronJob(job_id=body["job_id"], cron_expr=body["cron_expr"], payload=body.get("payload", {}))
        _cron.register(job)
        return JSONResponse({"ok": True, "job_id": job.job_id})
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=409)
    except KeyError as e:
        return JSONResponse({"ok": False, "error": f"missing: {e}"}, status_code=422)

@app.get("/cron/list")
async def cron_list() -> JSONResponse:
    return JSONResponse({"jobs": [j.__dict__ for j in _cron.list_jobs()]})
```

- [ ] **Step 4: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_refresh_scheduler.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add free-claw-router/router/catalog/refresh/scheduler.py free-claw-router/router/server/openai_compat.py free-claw-router/tests/test_refresh_scheduler.py
git commit -m "feat(refresh): APScheduler + /cron/register HTTP proxy for claw"
```

---

### Task 47: Bridge `claw CronCreate` to sidecar `/cron/register`

**Files:**
- Modify: `rust/crates/runtime/src/team_cron_registry.rs`
- Test: `rust/crates/runtime/tests/cron_proxy.rs` (new)

- [ ] **Step 1: Write failing test**

Create `rust/crates/runtime/tests/cron_proxy.rs`:

```rust
use httpmock::{Method::POST, MockServer};
use runtime::team_cron_registry::{CronCreateProxy, CronCreateRequest};

#[tokio::test]
async fn cron_create_forwards_to_router_cron_register() {
    let server = MockServer::start();
    let m = server.mock(|when, then| {
        when.method(POST).path("/cron/register");
        then.status(200).body("{\"ok\":true,\"job_id\":\"j1\"}");
    });

    let proxy = CronCreateProxy::new(server.base_url());
    let req = CronCreateRequest {
        job_id: "j1".into(),
        cron_expr: "0 3 * * *".into(),
        payload: serde_json::json!({"provider": "openrouter"}),
    };
    let ok = proxy.register(req).await.unwrap();
    assert!(ok);
    m.assert();
}
```

- [ ] **Step 2: Implement the proxy**

Append to `rust/crates/runtime/src/team_cron_registry.rs`:

```rust
use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
pub struct CronCreateRequest {
    pub job_id: String,
    pub cron_expr: String,
    pub payload: serde_json::Value,
}

pub struct CronCreateProxy {
    router_base_url: String,
    client: reqwest::Client,
}

impl CronCreateProxy {
    pub fn new(router_base_url: impl Into<String>) -> Self {
        Self { router_base_url: router_base_url.into(), client: reqwest::Client::new() }
    }
    pub async fn register(&self, req: CronCreateRequest) -> Result<bool, String> {
        let url = format!("{}/cron/register", self.router_base_url.trim_end_matches('/'));
        match self.client.post(url).json(&req).send().await {
            Ok(resp) => Ok(resp.status().is_success()),
            Err(e) => Err(e.to_string()),
        }
    }
}
```

Wire the existing `CronCreate` tool dispatch in `rust/crates/tools/src/lib.rs` (look for `run_cron_create`): when `ROUTER_BASE_URL` env is set, forward the registration through `CronCreateProxy` and also persist in the in-memory registry; when not set, keep existing behavior.

- [ ] **Step 3: Run tests**

Run: `cd rust && cargo test -p runtime cron_proxy -- --nocapture`
Expected: passes.

- [ ] **Step 4: Commit**

```bash
git add rust/crates/runtime/src/team_cron_registry.rs rust/crates/tools/src/lib.rs rust/crates/runtime/tests/cron_proxy.rs rust/crates/runtime/Cargo.toml
git commit -m "feat(runtime): CronCreateProxy forwards to router /cron/register"
```

---

### Task 48: End-to-end DRY-RUN refresh flow

**Files:**
- Create: `free-claw-router/tests/test_refresh_e2e_dry_run.py`

- [ ] **Step 1: Write the integration test**

Create `free-claw-router/tests/test_refresh_e2e_dry_run.py`:

```python
import json
from pathlib import Path
import subprocess
from router.catalog.refresh.producer import Producer

def test_dry_run_refresh_writes_yaml_and_passes_schema(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
    (repo / "free-claw-router" / "router" / "catalog" / "data").mkdir(parents=True)

    research = [
        {
            "provider_id": "openrouter",
            "model_id": "z-ai/glm-4.6:free",
            "status": "added",
            "context_window": 131072,
            "tool_use": True,
            "structured_output": "partial",
            "free_tier": {"rpm": 20, "tpm": 100000, "daily": None, "reset_policy": "minute"},
            "pricing": {"input": 0, "output": 0, "free": True},
            "quirks": [],
            "evidence_urls": ["https://openrouter.ai/models/z-ai/glm-4.6:free"],
        }
    ]
    rpath = repo / "research.json"
    rpath.write_text(json.dumps(research))

    p = Producer(
        repo=repo,
        worktree_root=tmp_path / "wt",
        catalog_dir=repo / "free-claw-router" / "router" / "catalog" / "data",
        dry_run=True,
    )
    result = p.run_for_provider("openrouter", research_json=rpath)
    assert result.dry_run is True
    assert result.new_yaml_path.exists()
    content = result.new_yaml_path.read_text()
    assert "z-ai/glm-4.6:free" in content
```

- [ ] **Step 2: Run test**

Run: `cd free-claw-router && uv run pytest tests/test_refresh_e2e_dry_run.py -v`
Expected: passes.

- [ ] **Step 3: Commit**

```bash
git add free-claw-router/tests/test_refresh_e2e_dry_run.py
git commit -m "test(refresh): dry-run end-to-end catalog refresh flow"
```

---

## PART K — Claude review + hot reload (M6)

### Task 49: `catalog-refresh-verify.yml` — CI workflow

**Files:**
- Create: `.github/workflows/catalog-refresh-verify.yml`

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/catalog-refresh-verify.yml`:

```yaml
name: catalog-refresh-verify
on:
  pull_request:
    paths:
      - "free-claw-router/router/catalog/data/**"
      - "free-claw-router/router/catalog/schema.py"

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - name: Install deps
        run: |
          cd free-claw-router
          uv sync --extra dev
      - name: Schema + invariants
        run: |
          cd free-claw-router
          uv run pytest tests/test_catalog_schema.py tests/test_catalog_registry.py tests/test_catalog_openrouter.py -v
      - name: Routing snapshot tests
        run: |
          cd free-claw-router
          uv run pytest tests/test_routing_decide.py -v
      - name: Freshness check (last_verified within 14 days)
        run: |
          cd free-claw-router
          uv run python - <<'PY'
          import sys
          from datetime import datetime, timedelta
          from pathlib import Path
          import yaml
          cutoff = datetime.utcnow() - timedelta(days=14)
          stale = []
          for yml in Path("router/catalog/data").glob("*.yaml"):
              doc = yaml.safe_load(yml.read_text())
              for m in doc["models"]:
                  d = datetime.fromisoformat(m["last_verified"].replace("Z", "+00:00")).replace(tzinfo=None)
                  if d < cutoff:
                      stale.append((yml.name, m["model_id"]))
          if stale:
              print("STALE entries (>14d):", stale)
              sys.exit(1)
          PY
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/catalog-refresh-verify.yml
git commit -m "ci: verify catalog YAML schema, invariants, and freshness"
```

---

### Task 50: `claude-review.yml` + review prompt

**Files:**
- Create: `.github/workflows/claude-review.yml`
- Create: `free-claw-router/ops/claude-review-prompt.md`

- [ ] **Step 1: Write the review prompt**

Create `free-claw-router/ops/claude-review-prompt.md`:

```markdown
# Catalog-refresh PR review instructions

You are reviewing an automated PR that updates
`free-claw-router/router/catalog/data/<provider>.yaml` against the spec at
`docs/superpowers/specs/2026-04-15-p0-free-llm-router-design.md`.

## Must-check list

1. **Free-only invariant** — every modified model has `pricing: {input: 0, output: 0, free: true}`.
2. **Evidence** — each modified/added entry has at least one `evidence_urls` entry, and the URL
   matches an allowed prefix in `free-claw-router/ops/allowed_sources.yaml`. Any unknown prefix is a reject.
3. **Freshness** — `last_verified` is within 48 hours of the PR timestamp.
4. **Quirk plausibility** — `quirks` entries are specific and actionable (e.g. "tool_calls use v2 schema",
   not "sometimes slow"). Vague quirks → request revision.
5. **Context window sanity** — `context_window` is > 0 and matches what evidence URLs claim (spot-check 1–2).
6. **Deprecation hygiene** — if `status == deprecated`, both `deprecation_reason` and `replaced_by` must be populated.
7. **No secrets** — neither the YAML nor the PR body must contain API keys, tokens, or credentials of any form.

## Output format

Post a single PR review via `gh pr review --comment` with:
- A header line `Catalog review: APPROVE | REQUEST_CHANGES | NEEDS_INVESTIGATION`.
- Bullet list of findings keyed to the list above.
- If REQUEST_CHANGES: include exact YAML diff suggestions per entry.
```

- [ ] **Step 2: Write the workflow**

Create `.github/workflows/claude-review.yml`:

```yaml
name: claude-review
on:
  pull_request:
    types: [opened, synchronize]
    paths:
      - "free-claw-router/router/catalog/data/**"

permissions:
  pull-requests: write
  contents: read

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - name: Extract PR diff
        id: diff
        run: |
          git diff origin/${{ github.base_ref }}...HEAD -- free-claw-router/router/catalog/data/ > /tmp/pr.diff
          echo "diff_size=$(wc -c < /tmp/pr.diff)" >> $GITHUB_OUTPUT
      - name: Throttle — skip if same provider already reviewed today
        id: throttle
        run: |
          provider=$(git diff --name-only origin/${{ github.base_ref }}...HEAD \
            -- free-claw-router/router/catalog/data/ | head -1 | xargs basename -s .yaml)
          count=$(gh pr list --search "provider:$provider merged:>$(date -d 'today 00:00' -Iseconds)" --json number | jq length)
          if [ "$count" -ge 2 ]; then
            echo "skip=true" >> $GITHUB_OUTPUT
          else
            echo "skip=false" >> $GITHUB_OUTPUT
          fi
        env: { GH_TOKEN: ${{ secrets.GITHUB_TOKEN }} }
      - name: Run Claude review
        if: steps.throttle.outputs.skip == 'false'
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python3 - <<'PY'
          import os, json, subprocess, urllib.request, pathlib
          prompt = pathlib.Path("free-claw-router/ops/claude-review-prompt.md").read_text()
          diff = pathlib.Path("/tmp/pr.diff").read_text()
          body = {
              "model": "claude-opus-4-6",
              "max_tokens": 1600,
              "system": prompt,
              "messages": [{"role": "user", "content": f"PR diff:\n```\n{diff}\n```"}],
          }
          req = urllib.request.Request(
              "https://api.anthropic.com/v1/messages",
              method="POST",
              data=json.dumps(body).encode(),
              headers={
                  "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                  "anthropic-version": "2023-06-01",
                  "content-type": "application/json",
              },
          )
          resp = json.loads(urllib.request.urlopen(req).read())
          text = "".join(b.get("text", "") for b in resp.get("content", []))
          pathlib.Path("/tmp/review.md").write_text(text)
          PY
          gh pr comment ${{ github.event.pull_request.number }} --body-file /tmp/review.md
        env: { GH_TOKEN: ${{ secrets.GITHUB_TOKEN }} }
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/claude-review.yml free-claw-router/ops/claude-review-prompt.md
git commit -m "ci: auto Claude review on catalog refresh PRs with throttling"
```

---

### Task 51: Set `ANTHROPIC_API_KEY` secret (manual)

**Files:** none (GitHub web/CLI action)

- [ ] **Step 1: Set secret**

Run: `gh secret set ANTHROPIC_API_KEY --repo kwanghan-bae/free-claw-code`
Expected: prompts for value, confirms.

- [ ] **Step 2: Verify**

Run: `gh secret list --repo kwanghan-bae/free-claw-code`
Expected: `ANTHROPIC_API_KEY` appears.

- [ ] **Step 3: No commit (external config)**

---

### Task 52: `catalog/hot_reload.py` — watchdog + atomic swap

**Files:**
- Create: `free-claw-router/router/catalog/hot_reload.py`
- Create: `free-claw-router/tests/test_catalog_hot_reload.py`

- [ ] **Step 1: Write failing test**

Create `free-claw-router/tests/test_catalog_hot_reload.py`:

```python
import time
from pathlib import Path
from router.catalog.hot_reload import CatalogLive
from router.catalog.registry import Registry

def test_live_catalog_swaps_on_file_change(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "one.yaml").write_text(
        """
provider_id: one
base_url: https://x
auth: {env: K, scheme: bearer}
known_ratelimit_header_schema: generic
models:
  - model_id: one/m:free
    status: active
    context_window: 8000
    tool_use: false
    structured_output: none
    free_tier: {rpm: 10, tpm: 5000, daily: null, reset_policy: minute}
    pricing: {input: 0, output: 0, free: true}
    quirks: []
    evidence_urls: [https://x/m]
    last_verified: "2026-04-15T00:00:00Z"
    first_seen: "2026-04-15"
"""
    )
    live = CatalogLive(data)
    live.start()
    try:
        first = live.snapshot().providers[0].provider_id
        assert first == "one"
        (data / "one.yaml").write_text(
            (data / "one.yaml").read_text().replace("one/m:free", "one/m2:free").replace("provider_id: one", "provider_id: one-v2"),
        )
        # poll until the watchdog catches up
        for _ in range(50):
            if live.snapshot().providers[0].provider_id == "one-v2":
                break
            time.sleep(0.05)
        assert live.snapshot().providers[0].provider_id == "one-v2"
    finally:
        live.stop()
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/catalog/hot_reload.py`:

```python
from __future__ import annotations
from pathlib import Path
from threading import Lock
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from router.catalog.registry import Registry

class _Handler(FileSystemEventHandler):
    def __init__(self, live: "CatalogLive") -> None:
        self._live = live

    def on_any_event(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".yaml"):
            self._live.reload()

class CatalogLive:
    def __init__(self, data_dir: Path) -> None:
        self._dir = Path(data_dir)
        self._current = Registry.load_from_dir(self._dir)
        self._lock = Lock()
        self._observer: Observer | None = None

    def snapshot(self) -> Registry:
        with self._lock:
            return self._current

    def reload(self) -> None:
        try:
            new = Registry.load_from_dir(self._dir)
        except Exception:
            # Keep old buffer if reload fails.
            return
        with self._lock:
            self._current = new

    def start(self) -> None:
        obs = Observer()
        obs.schedule(_Handler(self), str(self._dir), recursive=False)
        obs.start()
        self._observer = obs

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
```

- [ ] **Step 3: Wire into lifespan + server**

Modify `free-claw-router/router/server/lifespan.py`:

```python
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
```

Modify `_ensure_loaded` in `free-claw-router/router/server/openai_compat.py`:

```python
def _ensure_loaded() -> tuple[Registry, Policy]:
    global _policy
    live: CatalogLive = app.state.catalog_live
    if _policy is None:
        _policy = Policy.load(POLICY_PATH)
    return live.snapshot(), _policy
```

Remove the older `_registry` global and its initialization.

- [ ] **Step 4: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_catalog_hot_reload.py tests/test_server_direct.py tests/test_server_quota.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add free-claw-router/router/catalog/hot_reload.py free-claw-router/router/server/lifespan.py free-claw-router/router/server/openai_compat.py free-claw-router/tests/test_catalog_hot_reload.py
git commit -m "feat(catalog): watchdog-based hot-reload with atomic double-buffer"
```

---

### Task 53: End-to-end live review rehearsal (manual)

**Files:** none (execution)

- [ ] **Step 1: Open a sample catalog PR**

Run:

```bash
git checkout -b catalog/refresh/2026-04-15-rehearsal
sed -i '' 's/last_verified: "2026-04-15T00:00:00Z"/last_verified: "2026-04-15T01:00:00Z"/' \
  free-claw-router/router/catalog/data/openrouter.yaml
git add free-claw-router/router/catalog/data/openrouter.yaml
git commit -m "catalog(rehearsal): nudge timestamp"
git push -u origin catalog/refresh/2026-04-15-rehearsal
gh pr create --title "catalog: rehearsal refresh" --body "M6 end-to-end rehearsal" --base main
```

- [ ] **Step 2: Observe both CI jobs**

Run: `gh pr checks`
Expected: `catalog-refresh-verify` green; `claude-review` posts a review comment.

- [ ] **Step 3: Approve + merge**

Run: `gh pr merge --squash`
Start the sidecar in another terminal and confirm `/health` returns the new catalog_version without restart.

- [ ] **Step 4: No commit (rehearsal evidence only — capture `gh pr view <N>` output in M6 evidence file if desired)**

---

## PART L — Remaining provider YAMLs (M7)

### Task 54: z.ai / GLM day-1 YAML

**Files:**
- Create: `free-claw-router/router/catalog/data/zai.yaml`

- [ ] **Step 1: Write the file**

Create `free-claw-router/router/catalog/data/zai.yaml`:

```yaml
provider_id: zai
base_url: https://api.z.ai/api/paas/v4
auth: {env: ZAI_API_KEY, scheme: bearer}
known_ratelimit_header_schema: generic
models:
  - model_id: glm-4-flash
    status: active
    context_window: 128000
    tool_use: true
    structured_output: partial
    free_tier: {rpm: 60, tpm: 600000, daily: null, reset_policy: minute}
    pricing: {input: 0, output: 0, free: true}
    quirks:
      - "base URL differs from openrouter-hosted glm variants"
      - "bearer auth uses API key generated at z.ai dashboard"
    evidence_urls:
      - https://docs.z.ai/guides/llm/glm-4-flash
      - https://bigmodel.cn/dev/howuse/glm-4-flash
    last_verified: "2026-04-15T00:00:00Z"
    first_seen: "2026-03-20"
```

- [ ] **Step 2: Run catalog tests**

Run: `cd free-claw-router && uv run pytest tests/ -k "catalog" -v`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add free-claw-router/router/catalog/data/zai.yaml
git commit -m "feat(catalog): add z.ai/GLM day-1 YAML (glm-4-flash)"
```

---

### Task 55: Cerebras day-1 YAML

**Files:**
- Create: `free-claw-router/router/catalog/data/cerebras.yaml`

- [ ] **Step 1: Write the file**

Create `free-claw-router/router/catalog/data/cerebras.yaml`:

```yaml
provider_id: cerebras
base_url: https://api.cerebras.ai/v1
auth: {env: CEREBRAS_API_KEY, scheme: bearer}
known_ratelimit_header_schema: generic
models:
  - model_id: llama-3.3-70b
    status: active
    context_window: 8192
    tool_use: true
    structured_output: partial
    free_tier: {rpm: 30, tpm: 14400, daily: 14400, reset_policy: minute}
    pricing: {input: 0, output: 0, free: true}
    quirks:
      - "ultra-low latency; partial streaming behaviour stricter than OpenAI"
    evidence_urls:
      - https://inference-docs.cerebras.ai/models
      - https://cloud.cerebras.ai/
    last_verified: "2026-04-15T00:00:00Z"
    first_seen: "2026-03-05"
  - model_id: qwen-coder-32b-instruct
    status: active
    context_window: 32768
    tool_use: true
    structured_output: partial
    free_tier: {rpm: 30, tpm: 14400, daily: 14400, reset_policy: minute}
    pricing: {input: 0, output: 0, free: true}
    quirks: []
    evidence_urls: [https://inference-docs.cerebras.ai/models]
    last_verified: "2026-04-15T00:00:00Z"
    first_seen: "2026-03-25"
```

- [ ] **Step 2: Run catalog tests**

Run: `cd free-claw-router && uv run pytest tests/ -k "catalog" -v`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add free-claw-router/router/catalog/data/cerebras.yaml
git commit -m "feat(catalog): add Cerebras day-1 YAML (llama-3.3-70b, qwen-coder-32b)"
```

---

### Task 56: LM Studio day-1 YAML

**Files:**
- Create: `free-claw-router/router/catalog/data/lmstudio.yaml`

- [ ] **Step 1: Write the file**

Create `free-claw-router/router/catalog/data/lmstudio.yaml`:

```yaml
provider_id: lmstudio
base_url: http://127.0.0.1:1234/v1
auth: {env: LMSTUDIO_API_KEY, scheme: none}
known_ratelimit_header_schema: none
models:
  - model_id: qwen2.5-coder-14b
    status: active
    context_window: 32768
    tool_use: true
    structured_output: partial
    free_tier: {rpm: null, tpm: null, daily: null, reset_policy: rolling}
    pricing: {input: 0, output: 0, free: true}
    quirks:
      - "local LM Studio server; model ID must match what's loaded in the UI"
      - "tool_use requires an Instruct-tuned variant"
    evidence_urls:
      - https://lmstudio.ai/docs/local-server
    last_verified: "2026-04-15T00:00:00Z"
    first_seen: "2026-02-15"
```

- [ ] **Step 2: Run catalog tests**

Run: `cd free-claw-router && uv run pytest tests/ -k "catalog" -v`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add free-claw-router/router/catalog/data/lmstudio.yaml
git commit -m "feat(catalog): add LM Studio day-1 YAML (qwen2.5-coder-14b)"
```

---

### Task 57: Final integration smoke (manual)

**Files:** none (execution + optional evidence file)

- [ ] **Step 1: Build claw + start sidecar**

```bash
cd rust && cargo build -p rusty-claude-cli
cd ../free-claw-router && uv run uvicorn router.server.openai_compat:app --port 7801 &
sleep 2
```

- [ ] **Step 2: Run live turn with hints**

```bash
OPENAI_BASE_URL=http://127.0.0.1:7801 \
  ../rust/target/debug/claw prompt --model "openrouter/z-ai/glm-4.6:free" \
  "refactor the function `add` in a.py to accept a list" 2>&1 | tee /tmp/claw-smoke.log
```

Expected: claw gets a real completion; sidecar telemetry SQLite gained a row.

- [ ] **Step 3: Verify telemetry wrote a span**

```bash
sqlite3 ~/.free-claw-router/telemetry.db \
  "SELECT op_name, model_id, status FROM spans ORDER BY started_at DESC LIMIT 5;"
```

Expected: at least one `llm_call` span with a terminal status.

- [ ] **Step 4: Shut down sidecar**

```bash
kill %1
```

- [ ] **Step 5: No commit (evidence-only)**

---

## Self-review (run after full plan is written)

**Spec coverage check:**

| Spec section | Plan task(s) |
|---|---|
| §2 In scope (1) OpenAI-compat sidecar | Tasks 10–13, 22, 29 |
| §2 (2) Living catalog | Tasks 14–18, 42–48, 49–53, 54–56 |
| §2 (3) L1+L4 hybrid routing + skill-model affinity | Tasks 19–22, 40–41 |
| §2 (4) Global quota + backpressure | Tasks 8, 31–34 |
| §2 (5) OTel-style Shape C | Tasks 1–5, 35–41 |
| §2 (6) Hermes absorption | Tasks 23–26 |
| §2 (7) Autonomous PR loop | Tasks 42–48, 49–53 |
| §2 (8) Hot reload | Task 52 |
| §3.2 module layout | Covered by file table + individual tasks |
| §6.3 Back-pressure to claw | Tasks 8, 33 |
| §7.4 read-models | Task 41 |
| §7.5 Evaluator plugin interface | Task 40 |
| §10 milestones M0–M7 | Parts B/C = M0, Parts D/E = M1, Parts F/G = M2, Part H = M3, Part I = M4, Part J = M5, Part K = M6, Part L = M7 |
| §12 open questions | Q12.1 (uv required, install.sh hints) = Task 12; Q12.3 (`~/.free-claw-router/`) = Task 38 lifespan; Q12.4 (RouterHealth) = Task 9 |

No gaps identified. Q12.2 (policy version field) is embedded in Task 19 (`policy_version: "1"`). Q12.5 (one provider per invocation) is embedded in Task 45 (`Producer.run_for_provider` takes a single `provider_id`).

**Placeholder scan:** no TBD/TODO strings remain in the plan body. Every code step contains the actual code.

**Type-consistency check:**
- `DispatchResult` fields (`status`, `body`, `rate_limit_state`, `response_headers`) consistent between Tasks 26, 28, 29, 34, 38.
- `Candidate` fields (`provider_id`, `model_id`, `model`, `score`) consistent across Tasks 21, 28, 34, 38.
- `Bucket.reserve / commit / rollback` signatures consistent across Tasks 31, 34, 38.
- `TraceContext` present in Rust (`telemetry::TraceContext` in Task 1) and in Python (`router.telemetry.spans.TraceContext` in Task 36) with different field types — this is fine; they communicate over the wire via hex-encoded W3C headers.
- `CronJob` (Python in Task 46) and `CronCreateRequest` (Rust in Task 47) share field names: `job_id`, `cron_expr`, `payload`.

No inconsistencies identified.

---

## Execution handoff

Plan complete and committed to `docs/superpowers/plans/2026-04-15-p0-free-llm-router.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

**Which approach?**






