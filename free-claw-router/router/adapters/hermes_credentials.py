"""Thin credential resolver. For M2 start, env-only.
Post-M3 this wraps Hermes' CredentialPool for multi-key rotation.
"""
from __future__ import annotations
import os

def resolve_api_key(env_name: str) -> str | None:
    val = os.environ.get(env_name, "").strip()
    return val or None
