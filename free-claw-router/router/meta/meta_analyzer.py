from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Awaitable, Callable
import yaml
from .meta_suggestions import MetaSuggestion

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """You are a meta-evolution analyzer. Given a session trajectory and the list of editable targets, suggest improvements to the agent's configuration and prompts.

## Editable targets
{targets}

## Rules
- Only suggest edits to files listed in targets
- edit_type must match the target's type (yaml, prompt_only, config_only)
- Be specific: include the exact change in proposed_diff
- confidence 0.0-1.0: how certain you are this will improve performance
- Return a JSON array. Return [] if no improvements needed.

Output format: [{{"target_file": "...", "edit_type": "...", "direction": "short description", "rationale": "why", "confidence": 0.0-1.0, "proposed_diff": "what to change"}}]"""


class MetaAnalyzer:
    def __init__(self, *, llm_fn: Callable[..., Awaitable[str]], targets_path: Path | None) -> None:
        self._llm = llm_fn
        self._valid_targets: set[str] = set()
        if targets_path and targets_path.exists():
            data = yaml.safe_load(targets_path.read_text())
            self._valid_targets = {t["path"] for t in data.get("targets", [])}

    async def analyze(self, *, trace_id: str, trajectory: dict) -> list[MetaSuggestion]:
        try:
            targets_desc = "\n".join(f"- {t}" for t in sorted(self._valid_targets)) if self._valid_targets else "(no targets loaded)"
            prompt = ANALYSIS_PROMPT.format(targets=targets_desc)
            raw = await self._llm(messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(trajectory, indent=2, default=str)[:6000]},
            ])
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
            items = json.loads(cleaned)
            if not isinstance(items, list):
                return []
            suggestions = []
            for item in items:
                tf = item.get("target_file", "")
                if self._valid_targets and tf not in self._valid_targets:
                    logger.debug("Filtered invalid target: %s", tf)
                    continue
                suggestions.append(MetaSuggestion(
                    trace_id=trace_id,
                    target_file=tf,
                    edit_type=item.get("edit_type", ""),
                    direction=item.get("direction", ""),
                    rationale=item.get("rationale", ""),
                    confidence=float(item.get("confidence", 0.5)),
                    proposed_diff=item.get("proposed_diff", ""),
                ))
            return suggestions
        except (json.JSONDecodeError, ValueError):
            logger.warning("Meta analyzer: unparseable output for %s", trace_id[:8])
            return []
        except Exception:
            logger.warning("Meta analyzer failed for %s", trace_id[:8], exc_info=True)
            return []
