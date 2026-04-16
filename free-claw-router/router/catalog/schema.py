from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

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
