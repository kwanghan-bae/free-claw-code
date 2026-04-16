"""Stub for openspace.prompts.SkillEnginePrompts.
These prompts are used by analyzer.py and evolver.py.
We inline minimal versions; can be expanded from upstream later."""


class SkillEnginePrompts:
    """Central registry of prompts used by the skill engine."""

    # Evolution self-assessment tokens
    EVOLUTION_COMPLETE = "<EVOLUTION_COMPLETE>"
    EVOLUTION_FAILED = "<EVOLUTION_FAILED>"

    @staticmethod
    def analysis_system() -> str:
        return "You are a skill execution analyzer. Given a task transcript, identify which skills were used, how they performed, and suggest improvements."

    @staticmethod
    def analysis_user(transcript: str, skills_context: str) -> str:
        return f"## Task Transcript\n{transcript}\n\n## Available Skills\n{skills_context}\n\nAnalyze the execution and suggest skill improvements."

    @staticmethod
    def evolution_system() -> str:
        return "You are a skill evolution agent. Given a skill and improvement suggestion, produce a minimal diff that fixes or enhances the skill."

    @staticmethod
    def evolution_user(skill_content: str, suggestion: str, context: str) -> str:
        return f"## Current Skill\n{skill_content}\n\n## Suggestion\n{suggestion}\n\n## Context\n{context}\n\nProduce the improved skill content."

    @staticmethod
    def execution_analysis(**kwargs) -> str:
        """Build the prompt for post-execution skill quality analysis."""
        parts = ["Analyze the following execution:\n"]
        for k, v in kwargs.items():
            parts.append(f"## {k}\n{v}\n")
        return "\n".join(parts)

    @staticmethod
    def evolution_fix(**kwargs) -> str:
        """Build the prompt for a FIX evolution."""
        parts = ["Fix the following skill:\n"]
        for k, v in kwargs.items():
            parts.append(f"## {k}\n{v}\n")
        return "\n".join(parts)

    @staticmethod
    def evolution_derived(**kwargs) -> str:
        """Build the prompt for a DERIVED evolution."""
        parts = ["Derive an enhanced version of the following skill:\n"]
        for k, v in kwargs.items():
            parts.append(f"## {k}\n{v}\n")
        return "\n".join(parts)

    @staticmethod
    def evolution_captured(**kwargs) -> str:
        """Build the prompt for a CAPTURED evolution."""
        parts = ["Capture the following pattern as a new skill:\n"]
        for k, v in kwargs.items():
            parts.append(f"## {k}\n{v}\n")
        return "\n".join(parts)

    @staticmethod
    def evolution_confirm(**kwargs) -> str:
        """Build the prompt for LLM confirmation of evolution candidates."""
        parts = ["Confirm whether this skill needs evolution:\n"]
        for k, v in kwargs.items():
            parts.append(f"## {k}\n{v}\n")
        return "\n".join(parts)
