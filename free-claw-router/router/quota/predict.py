from __future__ import annotations
from enum import Enum

class Affordability(str, Enum):
    SUFFICIENT = "sufficient"
    TIGHT = "tight"
    INSUFFICIENT = "insufficient"

def estimate_request_tokens(payload: dict) -> int:
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
