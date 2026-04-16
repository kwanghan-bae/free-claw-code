# P1 — Mempalace Ultra-Long-Term Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate mempalace into the claw + sidecar stack so every session's context is preserved, recoverable on wake-up, and searchable by the agent via MCP.

**Architecture:** Two-path integration — MCP for agent-driven search (claw → mempalace MCP server), sidecar for infrastructure (wake-up injection into system messages, auto mining on session close, idle mining at 30min). Per-project wing + user wing in ChromaDB. Dual mining (convos + general).

**Tech Stack:** Python 3.12+ (mempalace library import, FastAPI sidecar extension), Rust (3-line header addition in prompt.rs), ChromaDB (local, via mempalace), APScheduler (already in sidecar).

**Spec reference:** `docs/superpowers/specs/2026-04-16-p1-mempalace-memory-design.md` (commit `e38cd13`).

---

## File Structure

### Sidecar (new `router/memory/` package)

| File | Responsibility |
|---|---|
| `free-claw-router/router/memory/__init__.py` | Package init |
| `free-claw-router/router/memory/wing_manager.py` | Workspace path → wing name mapping + SQLite persistence |
| `free-claw-router/router/memory/wakeup.py` | Call mempalace `wake_up` for project + user wings, TTL cache |
| `free-claw-router/router/memory/injector.py` | First-request detection + system message prepend |
| `free-claw-router/router/memory/transcript.py` | Telemetry spans/events → conversation transcript reconstruction |
| `free-claw-router/router/memory/miner.py` | Dual-mode mine (convos + general) with wing/room routing |
| `free-claw-router/router/memory/idle_detector.py` | Track last-request timestamp, trigger mining after 30min idle |

### Sidecar (modify existing)

| File | Change |
|---|---|
| `free-claw-router/router/server/openai_compat.py` | 3 lines: import + call `maybe_inject_wakeup` |
| `free-claw-router/router/server/lifespan.py` | Initialize idle_detector on startup |
| `free-claw-router/pyproject.toml` | Add `mempalace` dependency |

### Rust (minimal)

| File | Change |
|---|---|
| `rust/crates/runtime/src/prompt.rs` | Emit `x-free-claw-workspace` header (~3 lines) |
| `rust/crates/api/src/providers/anthropic.rs` | Accept + forward `workspace` header (same pattern as hints) |
| `rust/crates/api/src/providers/openai_compat.rs` | Same |
| `rust/crates/api/src/client.rs` | `ProviderClient::set_workspace` + `with_workspace` |

### Config

| File | Change |
|---|---|
| `.claude.json` | Add `mcpServers.mempalace` entry |

### Telemetry DB (migration)

| File | Change |
|---|---|
| `free-claw-router/router/telemetry/migrations/002_memory.sql` | `wing_mappings` + `mining_state` tables |

---

## Prerequisites

- [ ] mempalace is installed in sidecar venv: `cd free-claw-router && uv add mempalace`
- [ ] mempalace palace exists: `mempalace init ~/projects` (or any path — the system creates wings on first write)
- [ ] ChromaDB accessible at `~/.mempalace/palace` (default)

---

## PART A — Wing manager + telemetry migration (M0 foundation)

### Task 1: SQLite migration for wing_mappings + mining_state

**Files:**
- Create: `free-claw-router/router/telemetry/migrations/002_memory.sql`
- Create: `free-claw-router/tests/test_memory_migration.py`

- [ ] **Step 1: Write failing test**

Create `free-claw-router/tests/test_memory_migration.py`:

```python
from pathlib import Path
from router.telemetry.store import Store

def test_memory_tables_created_after_migration(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    with s.connect() as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "wing_mappings" in names
    assert "mining_state" in names

def test_wing_mappings_crud(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    with s.connect() as c:
        c.execute("INSERT INTO wing_mappings(workspace_path, wing_name) VALUES(?, ?)",
                  ("/Users/joel/Desktop/git/free-claw-code", "free-claw-code"))
        row = c.execute("SELECT wing_name FROM wing_mappings WHERE workspace_path = ?",
                        ("/Users/joel/Desktop/git/free-claw-code",)).fetchone()
    assert row[0] == "free-claw-code"

def test_mining_state_crud(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    with s.connect() as c:
        c.execute("INSERT INTO mining_state(trace_id, last_mined_event_ts, last_mined_at) VALUES(?, ?, ?)",
                  (b"\x01" * 16, 1000, 2000))
        row = c.execute("SELECT last_mined_event_ts FROM mining_state WHERE trace_id = ?",
                        (b"\x01" * 16,)).fetchone()
    assert row[0] == 1000
```

- [ ] **Step 2: Write migration**

Create `free-claw-router/router/telemetry/migrations/002_memory.sql`:

```sql
CREATE TABLE IF NOT EXISTS wing_mappings(
  workspace_path TEXT PRIMARY KEY,
  wing_name TEXT NOT NULL,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);

CREATE TABLE IF NOT EXISTS mining_state(
  trace_id BLOB PRIMARY KEY,
  last_mined_event_ts INTEGER NOT NULL,
  last_mined_at INTEGER NOT NULL
);
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_memory_migration.py -v`
Expected: 3 pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/telemetry/migrations/002_memory.sql free-claw-router/tests/test_memory_migration.py
git commit -m "feat(telemetry): add wing_mappings + mining_state tables (P1 migration)"
```

---

### Task 2: wing_manager.py

**Files:**
- Create: `free-claw-router/router/memory/__init__.py`
- Create: `free-claw-router/router/memory/wing_manager.py`
- Create: `free-claw-router/tests/test_memory_wing_manager.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_memory_wing_manager.py`:

```python
from pathlib import Path
from router.memory.wing_manager import WingManager
from router.telemetry.store import Store

def test_resolve_extracts_basename(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    wm = WingManager(store=s)
    assert wm.resolve("/Users/joel/Desktop/git/free-claw-code") == "free-claw-code"

def test_resolve_persists_mapping(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    wm = WingManager(store=s)
    wm.resolve("/Users/joel/Desktop/git/free-claw-code")
    wm2 = WingManager(store=s)
    assert wm2.resolve("/Users/joel/Desktop/git/free-claw-code") == "free-claw-code"

def test_resolve_returns_default_when_no_workspace(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    wm = WingManager(store=s)
    assert wm.resolve(None) == "default"
    assert wm.resolve("") == "default"

def test_user_wing_is_always_user(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    wm = WingManager(store=s)
    assert wm.user_wing == "user"
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/memory/__init__.py` (empty).

Create `free-claw-router/router/memory/wing_manager.py`:

```python
from __future__ import annotations
from pathlib import Path
from router.telemetry.store import Store


class WingManager:
    user_wing: str = "user"

    def __init__(self, store: Store) -> None:
        self._store = store

    def resolve(self, workspace_path: str | None) -> str:
        if not workspace_path or not workspace_path.strip():
            return "default"
        wing = Path(workspace_path.strip()).name
        if not wing:
            return "default"
        self._persist(workspace_path.strip(), wing)
        return wing

    def _persist(self, workspace_path: str, wing_name: str) -> None:
        with self._store.connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO wing_mappings(workspace_path, wing_name) VALUES(?, ?)",
                (workspace_path, wing_name),
            )
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_memory_wing_manager.py -v`
Expected: 4 pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/memory/__init__.py free-claw-router/router/memory/wing_manager.py free-claw-router/tests/test_memory_wing_manager.py
git commit -m "feat(memory): wing_manager — workspace path to wing name mapping"
```

---

## PART B — Wake-up + injection (M0)

### Task 3: wakeup.py — mempalace wake_up with TTL cache

**Files:**
- Create: `free-claw-router/router/memory/wakeup.py`
- Create: `free-claw-router/tests/test_memory_wakeup.py`
- Modify: `free-claw-router/pyproject.toml` (add `mempalace` dependency)

- [ ] **Step 1: Add mempalace dependency**

Run: `cd free-claw-router && uv add mempalace && uv sync --extra dev`

- [ ] **Step 2: Write failing tests**

Create `free-claw-router/tests/test_memory_wakeup.py`:

```python
import time
from unittest.mock import MagicMock, patch
from router.memory.wakeup import WakeupService

def test_wakeup_combines_project_and_user_wings():
    mock_palace = MagicMock()
    mock_palace.wake_up.side_effect = lambda wing=None: f"[wake:{wing}]"
    with patch("router.memory.wakeup._get_palace", return_value=mock_palace):
        svc = WakeupService(ttl_seconds=300)
        result = svc.get_wakeup("free-claw-code")
    assert "[wake:free-claw-code]" in result
    assert "[wake:user]" in result

def test_wakeup_caches_within_ttl():
    mock_palace = MagicMock()
    call_count = 0
    def fake_wake_up(wing=None):
        nonlocal call_count
        call_count += 1
        return f"[wake:{wing}:{call_count}]"
    mock_palace.wake_up.side_effect = fake_wake_up
    with patch("router.memory.wakeup._get_palace", return_value=mock_palace):
        svc = WakeupService(ttl_seconds=300)
        r1 = svc.get_wakeup("proj")
        r2 = svc.get_wakeup("proj")
    assert r1 == r2
    assert call_count == 2  # project + user, called once each

def test_wakeup_invalidate_clears_cache():
    mock_palace = MagicMock()
    mock_palace.wake_up.return_value = "text"
    with patch("router.memory.wakeup._get_palace", return_value=mock_palace):
        svc = WakeupService(ttl_seconds=300)
        svc.get_wakeup("proj")
        svc.invalidate("proj")
        svc.get_wakeup("proj")
    assert mock_palace.wake_up.call_count == 4  # 2 initial + 2 after invalidate

def test_wakeup_returns_empty_on_error():
    mock_palace = MagicMock()
    mock_palace.wake_up.side_effect = RuntimeError("chromadb down")
    with patch("router.memory.wakeup._get_palace", return_value=mock_palace):
        svc = WakeupService(ttl_seconds=300)
        result = svc.get_wakeup("proj")
    assert result == ""
```

- [ ] **Step 3: Implement**

Create `free-claw-router/router/memory/wakeup.py`:

```python
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def _get_palace():
    from mempalace.layers import PalaceLayer
    return PalaceLayer()


@dataclass
class _CacheEntry:
    text: str
    expires_at: float


class WakeupService:
    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}

    def get_wakeup(self, project_wing: str) -> str:
        cache_key = project_wing
        now = time.time()
        cached = self._cache.get(cache_key)
        if cached and cached.expires_at > now:
            return cached.text
        try:
            palace = _get_palace()
            project_text = palace.wake_up(wing=project_wing) or ""
            user_text = palace.wake_up(wing="user") or ""
        except Exception:
            logger.warning("mempalace wake_up failed", exc_info=True)
            return ""
        combined = ""
        if project_text.strip():
            combined += f"### Project: {project_wing}\n{project_text.strip()}\n\n"
        if user_text.strip():
            combined += f"### Your preferences & patterns\n{user_text.strip()}\n"
        self._cache[cache_key] = _CacheEntry(text=combined, expires_at=now + self._ttl)
        return combined

    def invalidate(self, project_wing: str) -> None:
        self._cache.pop(project_wing, None)
```

- [ ] **Step 4: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_memory_wakeup.py -v`
Expected: 4 pass.

- [ ] **Step 5: Commit**

```bash
git add free-claw-router/pyproject.toml free-claw-router/uv.lock free-claw-router/router/memory/wakeup.py free-claw-router/tests/test_memory_wakeup.py
git commit -m "feat(memory): wakeup service with project+user wing merge and TTL cache"
```

---

### Task 4: injector.py — first-request system message prepend

**Files:**
- Create: `free-claw-router/router/memory/injector.py`
- Create: `free-claw-router/tests/test_memory_injector.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_memory_injector.py`:

```python
from router.memory.injector import Injector

def _make_payload(system_content="You are helpful.", user_content="hello"):
    return {
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]
    }

def test_injects_on_first_request_for_trace():
    inj = Injector(wakeup_fn=lambda wing: f"[memory:{wing}]")
    payload = _make_payload()
    result = inj.maybe_inject(payload, trace_id="t1", workspace="/a/b/myproject", last_request_gap_seconds=0)
    assert "## Memory Context" in result["messages"][0]["content"]
    assert "[memory:myproject]" in result["messages"][0]["content"]

def test_skips_on_repeat_request_same_trace():
    inj = Injector(wakeup_fn=lambda wing: "[mem]")
    inj.maybe_inject(_make_payload(), trace_id="t1", workspace="/a/b/p", last_request_gap_seconds=0)
    payload2 = _make_payload()
    result = inj.maybe_inject(payload2, trace_id="t1", workspace="/a/b/p", last_request_gap_seconds=5)
    assert "## Memory Context" not in result["messages"][0]["content"]

def test_reinjects_after_idle_gap():
    inj = Injector(wakeup_fn=lambda wing: "[refreshed]", idle_threshold_seconds=1800)
    inj.maybe_inject(_make_payload(), trace_id="t1", workspace="/a/b/p", last_request_gap_seconds=0)
    payload2 = _make_payload()
    result = inj.maybe_inject(payload2, trace_id="t1", workspace="/a/b/p", last_request_gap_seconds=2000)
    assert "[refreshed]" in result["messages"][0]["content"]

def test_creates_system_message_if_missing():
    inj = Injector(wakeup_fn=lambda wing: "[mem]")
    payload = {"messages": [{"role": "user", "content": "hi"}]}
    result = inj.maybe_inject(payload, trace_id="t2", workspace="/a/b/p", last_request_gap_seconds=0)
    assert result["messages"][0]["role"] == "system"
    assert "[mem]" in result["messages"][0]["content"]

def test_returns_unmodified_when_wakeup_empty():
    inj = Injector(wakeup_fn=lambda wing: "")
    payload = _make_payload()
    result = inj.maybe_inject(payload, trace_id="t3", workspace="/a/b/p", last_request_gap_seconds=0)
    assert "## Memory Context" not in result["messages"][0]["content"]
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/memory/injector.py`:

```python
from __future__ import annotations
import copy
from pathlib import Path
from typing import Callable


MEMORY_HEADER = "\n\n## Memory Context (auto-injected by mempalace)\n\n"


class Injector:
    def __init__(
        self,
        wakeup_fn: Callable[[str], str],
        idle_threshold_seconds: int = 1800,
    ) -> None:
        self._wakeup_fn = wakeup_fn
        self._idle_threshold = idle_threshold_seconds
        self._injected_traces: dict[str, float] = {}  # trace_id -> last_inject_ts

    def maybe_inject(
        self,
        payload: dict,
        *,
        trace_id: str,
        workspace: str | None,
        last_request_gap_seconds: float,
    ) -> dict:
        should_inject = False
        if trace_id not in self._injected_traces:
            should_inject = True
        elif last_request_gap_seconds >= self._idle_threshold:
            should_inject = True

        if not should_inject:
            return payload

        wing = Path(workspace).name if workspace else "default"
        wakeup_text = self._wakeup_fn(wing)
        if not wakeup_text.strip():
            return payload

        payload = copy.deepcopy(payload)
        messages = payload.setdefault("messages", [])

        block = MEMORY_HEADER + wakeup_text

        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = messages[0].get("content", "") + block
        else:
            messages.insert(0, {"role": "system", "content": block.lstrip()})

        self._injected_traces[trace_id] = 0.0
        return payload
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_memory_injector.py -v`
Expected: 5 pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/memory/injector.py free-claw-router/tests/test_memory_injector.py
git commit -m "feat(memory): injector — first-request wake-up system message prepend"
```

---

### Task 5: Wire injector into openai_compat.py + lifespan

**Files:**
- Modify: `free-claw-router/router/server/openai_compat.py`
- Modify: `free-claw-router/router/server/lifespan.py`
- Create: `free-claw-router/tests/test_memory_injection_e2e.py`

- [ ] **Step 1: Write failing test**

Create `free-claw-router/tests/test_memory_injection_e2e.py`:

```python
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from router.server.openai_compat import app, _dispatch
from router.dispatch.client import DispatchResult
from router.adapters.hermes_ratelimit import RateLimitState
import router.server.openai_compat as mod

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def test_first_request_contains_memory_context(client, monkeypatch):
    captured_payload = {}
    async def fake_call(provider, model, payload, upstream_headers, *, timeout=60.0):
        captured_payload.update(payload)
        return DispatchResult(200, {"choices": [{"message": {"content": "hi"}}]}, RateLimitState(), {})
    monkeypatch.setattr(_dispatch, "call", fake_call)

    with patch("router.memory.wakeup._get_palace") as mock_palace_fn:
        mock_palace = mock_palace_fn.return_value
        mock_palace.wake_up.return_value = "You decided to use GraphQL."

        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "hi"}]},
            headers={"x-free-claw-hints": "chat", "x-free-claw-workspace": "/a/b/testproject",
                     "traceparent": "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1-bbbbbbbbbbbbbbbb-01"},
        )
    assert r.status_code == 200
    system_msg = captured_payload["messages"][0]["content"]
    assert "Memory Context" in system_msg
```

- [ ] **Step 2: Wire into lifespan**

Modify `free-claw-router/router/server/lifespan.py` — add memory initialization:

```python
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
```

- [ ] **Step 3: Wire into chat_completions**

In `free-claw-router/router/server/openai_compat.py`, in `chat_completions`, after `payload = await request.json()` and before routing logic, add:

```python
    # Memory injection (P1)
    injector = getattr(app.state, "injector", None)
    if injector is not None:
        _workspace = request.headers.get("x-free-claw-workspace")
        _trace_hex = ctx.trace_id.hex() if ctx else ""
        _gap = _request_gap_tracker.get_gap(_trace_hex)
        payload = injector.maybe_inject(
            payload, trace_id=_trace_hex, workspace=_workspace,
            last_request_gap_seconds=_gap,
        )
```

Add a simple request-gap tracker at module level:

```python
import time as _time

class _RequestGapTracker:
    def __init__(self):
        self._last_ts: dict[str, float] = {}
    def get_gap(self, trace_id: str) -> float:
        now = _time.time()
        last = self._last_ts.get(trace_id, now)
        self._last_ts[trace_id] = now
        return now - last

_request_gap_tracker = _RequestGapTracker()
```

- [ ] **Step 4: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_memory_injection_e2e.py tests/test_server_dispatch.py tests/test_server_telemetry.py -v`
Expected: all pass (no regressions).

- [ ] **Step 5: Commit**

```bash
git add free-claw-router/router/server/openai_compat.py free-claw-router/router/server/lifespan.py free-claw-router/tests/test_memory_injection_e2e.py
git commit -m "feat(server): wire wake-up injection into chat_completions (M0 complete)"
```

---

## PART C — Transcript + mining (M1)

### Task 6: transcript.py — reconstruct conversation from telemetry

**Files:**
- Create: `free-claw-router/router/memory/transcript.py`
- Create: `free-claw-router/tests/test_memory_transcript.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_memory_transcript.py`:

```python
import json
from pathlib import Path
from router.telemetry.store import Store
from router.memory.transcript import build_transcript

def _seed(store: Store, trace_id: bytes):
    store.insert_trace(trace_id=trace_id, started_at_ms=1000, root_op="session",
                       root_session_id="s1", catalog_version="v", policy_version="1")
    sid1 = b"\x01" * 8
    store.insert_span(span_id=sid1, trace_id=trace_id, parent_span_id=None,
                      op_name="llm_call", model_id="groq/llama", provider_id="groq",
                      skill_id=None, task_type="coding", started_at_ms=1000)
    store.insert_event(span_id=sid1, kind="request",
                       payload_json=json.dumps({"messages": [{"role": "user", "content": "refactor auth"}]}),
                       ts_ms=1000)
    store.insert_event(span_id=sid1, kind="dispatch_succeeded",
                       payload_json=json.dumps({"data": {"provider_id": "groq", "model_id": "llama"}}),
                       ts_ms=1100)
    # Simulate assistant response stored as event
    store.insert_event(span_id=sid1, kind="response",
                       payload_json=json.dumps({"choices": [{"message": {"role": "assistant", "content": "Done, I refactored the auth module."}}]}),
                       ts_ms=1200)

def test_build_transcript_returns_markdown(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    tid = b"\xaa" * 16
    _seed(s, tid)
    text = build_transcript(s, trace_id=tid)
    assert "refactor auth" in text
    assert "refactored the auth module" in text

def test_build_transcript_delta_skips_already_mined(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    tid = b"\xbb" * 16
    _seed(s, tid)
    text = build_transcript(s, trace_id=tid, after_ts=1150)
    assert "refactor auth" not in text  # event at ts=1000 skipped
    assert "refactored the auth module" in text  # event at ts=1200 included

def test_build_transcript_empty_when_no_events(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    text = build_transcript(s, trace_id=b"\xcc" * 16)
    assert text.strip() == ""
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/memory/transcript.py`:

```python
from __future__ import annotations
import json
from router.telemetry.store import Store


def build_transcript(store: Store, *, trace_id: bytes, after_ts: int = 0) -> str:
    with store.connect() as c:
        rows = list(c.execute(
            """SELECT e.kind, e.payload_json, e.ts
               FROM events e
               JOIN spans s ON e.span_id = s.span_id
               WHERE s.trace_id = ? AND e.ts > ?
               ORDER BY e.ts ASC""",
            (trace_id, after_ts),
        ))
    parts: list[str] = []
    for kind, payload_json, ts in rows:
        try:
            data = json.loads(payload_json)
        except json.JSONDecodeError:
            continue
        if kind == "request":
            for msg in data.get("messages", []):
                if msg.get("role") == "user":
                    parts.append(f"**User:** {msg.get('content', '')}\n")
        elif kind == "response":
            for choice in data.get("choices", []):
                msg = choice.get("message", {})
                if msg.get("role") == "assistant":
                    parts.append(f"**Assistant:** {msg.get('content', '')}\n")
    return "\n---\n".join(parts) if parts else ""
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_memory_transcript.py -v`
Expected: 3 pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/memory/transcript.py free-claw-router/tests/test_memory_transcript.py
git commit -m "feat(memory): transcript reconstruction from telemetry events"
```

---

### Task 7: miner.py — dual-mode mempalace mining

**Files:**
- Create: `free-claw-router/router/memory/miner.py`
- Create: `free-claw-router/tests/test_memory_miner.py`

- [ ] **Step 1: Write failing tests**

Create `free-claw-router/tests/test_memory_miner.py`:

```python
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from router.memory.miner import MemoryMiner

def test_mine_session_calls_convos_and_general():
    calls = []
    def fake_mine_convos(convo_dir, palace_path, wing=None, **kw):
        calls.append(("convos", wing))
    def fake_extract(text, **kw):
        calls.append(("general", None))
        return [
            {"content": "decided to use REST", "memory_type": "decision", "chunk_index": 0},
            {"content": "prefers TDD", "memory_type": "preference", "chunk_index": 1},
        ]
    mock_add = MagicMock()

    with patch("router.memory.miner.mine_convos", fake_mine_convos), \
         patch("router.memory.miner.extract_memories", fake_extract), \
         patch("router.memory.miner._add_drawer", mock_add):
        m = MemoryMiner(palace_path="/tmp/palace")
        m.mine_session("This is a test transcript.", project_wing="myproj")

    assert ("convos", "myproj") in calls
    assert ("general", None) in calls
    # preferences go to user wing
    user_calls = [c for c in mock_add.call_args_list if c.kwargs.get("wing") == "user"]
    assert len(user_calls) >= 1

def test_mine_session_handles_empty_transcript():
    m = MemoryMiner(palace_path="/tmp/palace")
    m.mine_session("", project_wing="proj")  # should not raise

def test_mine_session_handles_extraction_error():
    with patch("router.memory.miner.mine_convos", side_effect=RuntimeError("fail")), \
         patch("router.memory.miner.extract_memories", return_value=[]):
        m = MemoryMiner(palace_path="/tmp/palace")
        m.mine_session("some text", project_wing="proj")  # should not raise
```

- [ ] **Step 2: Implement**

Create `free-claw-router/router/memory/miner.py`:

```python
from __future__ import annotations
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_PALACE_PATH = os.environ.get("MEMPALACE_PALACE_PATH", os.path.expanduser("~/.mempalace/palace"))


def mine_convos(convo_dir, palace_path, wing=None, **kw):
    from mempalace.convo_miner import mine_convos as _mine
    _mine(convo_dir, palace_path, wing=wing, **kw)


def extract_memories(text, **kw):
    from mempalace.general_extractor import extract_memories as _extract
    return _extract(text, **kw)


def _add_drawer(wing: str, room: str, content: str, palace_path: str):
    from mempalace.mcp_server import tool_add_drawer
    tool_add_drawer(wing=wing, room=room, content=content, source_file="auto-mining")


_ROOM_MAP = {
    "decision": "decisions",
    "problem": "problems",
    "milestone": "milestones",
    "preference": "preferences",
    "emotion": "conversations",
}


class MemoryMiner:
    def __init__(self, palace_path: str | None = None) -> None:
        self._palace_path = palace_path or _PALACE_PATH

    def mine_session(self, transcript: str, *, project_wing: str) -> None:
        if not transcript.strip():
            return
        self._mine_convos(transcript, project_wing)
        self._mine_general(transcript, project_wing)

    def _mine_convos(self, transcript: str, project_wing: str) -> None:
        try:
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / "session.md"
                p.write_text(transcript)
                mine_convos(td, self._palace_path, wing=project_wing)
        except Exception:
            logger.warning("convos mining failed", exc_info=True)

    def _mine_general(self, transcript: str, project_wing: str) -> None:
        try:
            memories = extract_memories(transcript)
        except Exception:
            logger.warning("general extraction failed", exc_info=True)
            return
        for mem in memories:
            mem_type = mem.get("memory_type", "")
            content = mem.get("content", "")
            if not content.strip():
                continue
            room = _ROOM_MAP.get(mem_type, "conversations")
            wing = "user" if mem_type == "preference" else project_wing
            try:
                _add_drawer(wing=wing, room=room, content=content, palace_path=self._palace_path)
            except Exception:
                logger.warning("add_drawer failed for %s/%s", wing, room, exc_info=True)
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_memory_miner.py -v`
Expected: 3 pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/memory/miner.py free-claw-router/tests/test_memory_miner.py
git commit -m "feat(memory): dual-mode miner (convos + general) with room routing"
```

---

### Task 8: Session-close mining integration

**Files:**
- Modify: `free-claw-router/router/server/openai_compat.py` (record request/response events)
- Modify: `free-claw-router/router/server/lifespan.py` (session-close detector)
- Create: `free-claw-router/tests/test_memory_session_close.py`

- [ ] **Step 1: Write failing test**

Create `free-claw-router/tests/test_memory_session_close.py`:

```python
import time
from unittest.mock import MagicMock, patch
from router.memory.idle_detector import SessionCloseDetector

def test_detects_session_close_after_timeout():
    miner = MagicMock()
    transcript_fn = MagicMock(return_value="User: hi\nAssistant: hello")
    detector = SessionCloseDetector(
        close_timeout_seconds=1,
        miner=miner,
        transcript_fn=transcript_fn,
        wakeup_invalidate_fn=lambda w: None,
        wing_resolve_fn=lambda t: "proj",
    )
    detector.record_activity(trace_id="t1", workspace="/a/b/proj")
    time.sleep(1.5)
    detector.check_and_mine()
    miner.mine_session.assert_called_once()
    assert "hi" in miner.mine_session.call_args[0][0]

def test_does_not_mine_active_session():
    miner = MagicMock()
    detector = SessionCloseDetector(
        close_timeout_seconds=300,
        miner=miner,
        transcript_fn=MagicMock(return_value=""),
        wakeup_invalidate_fn=lambda w: None,
        wing_resolve_fn=lambda t: "proj",
    )
    detector.record_activity(trace_id="t1", workspace="/a/b/proj")
    detector.check_and_mine()
    miner.mine_session.assert_not_called()
```

- [ ] **Step 2: Implement session-close detection in idle_detector.py**

Create `free-claw-router/router/memory/idle_detector.py`:

```python
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class _SessionState:
    workspace: str
    last_activity: float
    mined_close: bool = False
    idle_mined: bool = False


class SessionCloseDetector:
    def __init__(
        self,
        *,
        close_timeout_seconds: int = 300,
        idle_threshold_seconds: int = 1800,
        miner,  # MemoryMiner
        transcript_fn: Callable[[str], str],  # (trace_id) -> transcript text
        wakeup_invalidate_fn: Callable[[str], None],
        wing_resolve_fn: Callable[[str], str],  # workspace -> wing
    ) -> None:
        self._close_timeout = close_timeout_seconds
        self._idle_threshold = idle_threshold_seconds
        self._miner = miner
        self._transcript_fn = transcript_fn
        self._wakeup_invalidate = wakeup_invalidate_fn
        self._wing_resolve = wing_resolve_fn
        self._sessions: dict[str, _SessionState] = {}

    def record_activity(self, trace_id: str, workspace: str) -> None:
        if trace_id in self._sessions:
            self._sessions[trace_id].last_activity = time.time()
            self._sessions[trace_id].idle_mined = False  # reset on new activity
        else:
            self._sessions[trace_id] = _SessionState(
                workspace=workspace, last_activity=time.time()
            )

    def check_and_mine(self) -> None:
        now = time.time()
        to_remove: list[str] = []
        for trace_id, state in self._sessions.items():
            gap = now - state.last_activity
            if gap >= self._close_timeout and not state.mined_close:
                self._do_mine(trace_id, state, reason="close")
                state.mined_close = True
                to_remove.append(trace_id)
            elif gap >= self._idle_threshold and not state.idle_mined and not state.mined_close:
                self._do_mine(trace_id, state, reason="idle")
                state.idle_mined = True
                self._wakeup_invalidate(self._wing_resolve(state.workspace))
        for tid in to_remove:
            self._sessions.pop(tid, None)

    def _do_mine(self, trace_id: str, state: _SessionState, *, reason: str) -> None:
        try:
            transcript = self._transcript_fn(trace_id)
            if not transcript.strip():
                return
            wing = self._wing_resolve(state.workspace)
            self._miner.mine_session(transcript, project_wing=wing)
            logger.info("mined session %s (reason=%s, wing=%s)", trace_id[:8], reason, wing)
        except Exception:
            logger.warning("mining failed for %s", trace_id[:8], exc_info=True)
```

- [ ] **Step 3: Wire into lifespan as APScheduler job**

Modify `free-claw-router/router/server/lifespan.py` to add the detector + periodic job:

```python
from router.memory.miner import MemoryMiner
from router.memory.idle_detector import SessionCloseDetector
from router.memory.transcript import build_transcript
from router.memory.wing_manager import WingManager

# ... inside lifespan, after existing setup ...
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

    app.state.session_detector = session_detector
    app.state.wing_manager = wing_mgr
```

In `openai_compat.py` `chat_completions`, after the memory injection block, add:

```python
    # Record activity for session-close detection
    detector = getattr(app.state, "session_detector", None)
    if detector is not None:
        detector.record_activity(
            trace_id=_trace_hex,
            workspace=request.headers.get("x-free-claw-workspace", ""),
        )
```

- [ ] **Step 4: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_memory_session_close.py tests/test_memory_injection_e2e.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add free-claw-router/router/memory/idle_detector.py free-claw-router/router/server/lifespan.py free-claw-router/router/server/openai_compat.py free-claw-router/tests/test_memory_session_close.py
git commit -m "feat(memory): session-close + idle mining via APScheduler (M1+M2 complete)"
```

---

## PART D — Rust header + MCP registration (M3)

### Task 9: Emit x-free-claw-workspace header from Rust

**Files:**
- Modify: `rust/crates/runtime/src/prompt.rs`
- Modify: `rust/crates/api/src/providers/anthropic.rs`
- Modify: `rust/crates/api/src/providers/openai_compat.rs`
- Modify: `rust/crates/api/src/client.rs`

- [ ] **Step 1: Add workspace field + setter on providers**

Follow the exact pattern used for `with_hints` / `set_hints` (from P0 Task 7 commit `9a58634`):

In `rust/crates/api/src/providers/anthropic.rs`:
- Add `workspace: Option<String>` field
- Add `with_workspace(mut self, ws: impl Into<String>) -> Self` + `set_workspace(&mut self, ws: impl Into<String>)`
- In `build_request`, after hints header: `if let Some(ws) = self.workspace.as_deref() { req = req.header("x-free-claw-workspace", ws); }`

Same for `openai_compat.rs` (`send_raw_request`).

In `client.rs` (`ProviderClient`):
- `with_workspace`, `set_workspace` dispatching to variants.

In `runtime/src/prompt.rs`, add alongside the existing hint classification:

```rust
pub fn workspace_header(session: &Session) -> Option<String> {
    session.workspace_root.as_ref().map(|p| p.to_string_lossy().into_owned())
}
```

In `runtime/src/conversation.rs`, where `task_hint` is applied to `ApiRequest`, also set:
```rust
workspace: crate::prompt::workspace_header(&self.session),
```

(Add `pub workspace: Option<String>` to `ApiRequest`.)

In `tools/src/lib.rs` `ProviderRuntimeClient::stream`, wire `set_workspace` alongside `set_hints`.

- [ ] **Step 2: Run tests**

```bash
cd rust
cargo test -p runtime -p api -p tools
cargo fmt --check
cargo clippy -p runtime -p api -p tools --all-targets -- -D warnings
```

- [ ] **Step 3: Commit**

```bash
git add rust/crates/runtime/src/prompt.rs rust/crates/runtime/src/conversation.rs \
        rust/crates/api/src/providers/anthropic.rs rust/crates/api/src/providers/openai_compat.rs \
        rust/crates/api/src/client.rs rust/crates/tools/src/lib.rs
git commit -m "feat(runtime): emit x-free-claw-workspace header for mempalace wing resolution"
```

---

### Task 10: Register mempalace MCP server in .claude.json

**Files:**
- Modify: `.claude.json`

- [ ] **Step 1: Add MCP server entry**

Read current `.claude.json`, then add under (or create) `mcpServers`:

```json
{
  "mcpServers": {
    "mempalace": {
      "command": "python",
      "args": ["-m", "mempalace.mcp_server", "--palace", "~/.mempalace/palace"]
    }
  }
}
```

If `.claude.json` already has content, merge the `mcpServers` key.

- [ ] **Step 2: Commit**

```bash
git add .claude.json
git commit -m "feat(config): register mempalace MCP server for agent-driven search"
```

---

### Task 11: Record request/response events in telemetry for transcript mining

**Files:**
- Modify: `free-claw-router/router/server/openai_compat.py`
- Create: `free-claw-router/tests/test_memory_transcript_events.py`

- [ ] **Step 1: Write failing test**

Create `free-claw-router/tests/test_memory_transcript_events.py`:

```python
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from router.server.openai_compat import app, _dispatch
from router.dispatch.client import DispatchResult
from router.adapters.hermes_ratelimit import RateLimitState
from router.telemetry.store import Store
from router.memory.transcript import build_transcript
import router.server.openai_compat as mod

@pytest.fixture
def store(tmp_path):
    s = Store(path=tmp_path / "t.db")
    s.initialize()
    mod._telemetry_store = s
    yield s
    mod._telemetry_store = None

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def test_request_and_response_events_enable_transcript(store, client, monkeypatch):
    async def fake_call(provider, model, payload, upstream_headers, *, timeout=60.0):
        return DispatchResult(
            200,
            {"choices": [{"message": {"role": "assistant", "content": "I refactored it."}}]},
            RateLimitState(), {},
        )
    monkeypatch.setattr(_dispatch, "call", fake_call)

    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "refactor auth"}]},
        headers={"x-free-claw-hints": "coding",
                 "traceparent": "00-dddddddddddddddddddddddddddddddd-eeeeeeeeeeeeeeee-01"},
    )
    assert r.status_code == 200

    tid = bytes.fromhex("dddddddddddddddddddddddddddddddd")
    transcript = build_transcript(store, trace_id=tid)
    assert "refactor auth" in transcript
    assert "refactored it" in transcript
```

- [ ] **Step 2: Add request/response event recording**

In `openai_compat.py`, inside the `call_one` inner function (where dispatch happens), record the request and response as events:

Before dispatch:
```python
store.insert_event(span_id=span_id, kind="request",
    payload_json=json.dumps({"messages": payload.get("messages", [])}),
    ts_ms=int(time.time() * 1000))
```

After successful dispatch:
```python
store.insert_event(span_id=span_id, kind="response",
    payload_json=json.dumps(result.body),
    ts_ms=int(time.time() * 1000))
```

- [ ] **Step 3: Run tests**

Run: `cd free-claw-router && uv run pytest tests/test_memory_transcript_events.py -v`
Expected: passes.

Run full suite: `uv run pytest tests/ -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add free-claw-router/router/server/openai_compat.py free-claw-router/tests/test_memory_transcript_events.py
git commit -m "feat(telemetry): record request/response events for transcript mining"
```

---

## Self-review

**Spec coverage:**

| Spec section | Task(s) |
|---|---|
| §2 (1) Wake-up injection | Tasks 3-5 |
| §2 (2) Automatic session mining | Tasks 6-8 |
| §2 (3) Idle background mining | Task 8 (idle_detector) |
| §2 (4) Palace wing structure | Tasks 1-2 |
| §2 (5) Auto-fallback search | Native mempalace behavior (wing=None); no custom code needed |
| §2 (6) MCP server registration | Task 10 |
| §2 (7) Workspace header | Task 9 |
| §5 Wake-up injection detail | Tasks 3-5 |
| §6 Automatic mining detail | Tasks 6-8, 11 |
| §7 Error handling | Built into every module (try/except, never crash dispatch) |
| §8 Testing strategy | Tests in every task |
| §9 Milestones M0-M3 | M0=Task 5, M1=Task 8, M2=Task 8, M3=Task 10 |

**Placeholder scan:** No TBD/TODO found. All code blocks are complete.

**Type consistency:** `WakeupService.get_wakeup(wing)` signature matches `Injector(wakeup_fn=...)` usage. `SessionCloseDetector` callbacks match the types passed from lifespan. `build_transcript(store, trace_id=bytes)` matches the hex→bytes conversion in lifespan.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-16-p1-mempalace-memory.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
