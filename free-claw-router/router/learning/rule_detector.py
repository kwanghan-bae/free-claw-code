from __future__ import annotations
import re
from collections import defaultdict
from .nudge_cache import Nudge

_DECISION_RE = re.compile(
    r"(?:decided to|we chose|going with|switched to|will use)\s+(.{10,80})",
    re.IGNORECASE,
)
_LESSON_RE = re.compile(
    r"(?:failed because|bug was|lesson:|the issue was|root cause)\s+(.{10,120})",
    re.IGNORECASE,
)
_REMEMBER_RE = re.compile(
    r"(?:remember that|note that|important:)\s+(.{10,120})",
    re.IGNORECASE,
)
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")


class RuleDetector:
    def __init__(self) -> None:
        self._code_blocks: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._tool_failures: dict[str, int] = defaultdict(int)

    def scan(self, assistant_response: str) -> list[Nudge]:
        nudges: list[Nudge] = []
        for regex, ntype, conf in [
            (_DECISION_RE, "memory_save", 0.85),
            (_LESSON_RE, "memory_save", 0.80),
            (_REMEMBER_RE, "memory_save", 0.90),
        ]:
            for m in regex.finditer(assistant_response):
                nudges.append(Nudge(
                    nudge_type=ntype,
                    content=m.group(0).strip(),
                    source="rule",
                    confidence=conf,
                ))
        return nudges

    def record_code_block(self, trace_id: str, block: str) -> None:
        normalized = block.strip()
        self._code_blocks[trace_id][normalized] += 1

    def check_repeats(self, trace_id: str, block: str) -> list[Nudge]:
        normalized = block.strip()
        count = self._code_blocks[trace_id].get(normalized, 0)
        if count >= 3:
            return [Nudge(
                nudge_type="skill_create",
                content=f"Code pattern repeated {count}x — consider extracting as a reusable skill",
                source="rule",
                confidence=0.75,
            )]
        return []

    def record_tool_result(self, trace_id: str, *, success: bool) -> None:
        if success:
            self._tool_failures[trace_id] = 0
        else:
            self._tool_failures[trace_id] += 1

    def check_tool_failures(self, trace_id: str) -> list[Nudge]:
        if self._tool_failures.get(trace_id, 0) >= 3:
            self._tool_failures[trace_id] = 0
            return [Nudge(
                nudge_type="skill_fix",
                content="3+ consecutive tool failures — consider fixing the relevant skill",
                source="rule",
                confidence=0.80,
            )]
        return []
