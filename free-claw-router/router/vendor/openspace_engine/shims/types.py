"""Stub types for openspace.grounding, openspace.recording, etc."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class BaseTool:
    name: str = ""
    description: str = ""


class ToolQualityManager:
    def get_degraded_tools(self) -> list: return []
    def get_tool_record(self, name: str) -> Optional["ToolQualityRecord"]: return None


@dataclass
class ToolQualityRecord:
    tool_name: str = ""
    success_count: int = 0
    error_count: int = 0
    total_count: int = 0


class RecordingManager:
    def load_recording(self, path) -> dict: return {}


class BackendType(str, Enum):
    SHELL = "shell"
    SYSTEM = "system"


class LocalTool(BaseTool):
    pass
