from __future__ import annotations

_PLANNING = ("design", "architect", "plan", "approach", "strategy")
_CODING = (
    "refactor", "implement", "fix", "bug", "unit test",
    "integration test", "add function", "add method", "write tests", "patch",
)
_TOOL_HEAVY = ("run", "execute", "search", "grep", "shell")
_SUMMARY = ("summarize", "summary", "tl;dr", "condense")

def classify_task_hint(user_message: str) -> str:
    words: set[str] = set(user_message.lower().split())
    text = user_message.lower()
    if any(k in words for k in _PLANNING):
        return "planning"
    if any(k in words for k in _SUMMARY) or any(k in text for k in _SUMMARY):
        return "summary"
    if any(k in words for k in _TOOL_HEAVY):
        return "tool_heavy"
    # Multi-word phrases need substring match
    if any(k in text for k in _CODING):
        return "coding"
    return "chat"
