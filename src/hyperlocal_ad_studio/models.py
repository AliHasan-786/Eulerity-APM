from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal


@dataclass
class LocalContext:
    zip_code: str
    location_name: str
    market_tier: str
    demographics: str
    competition: str
    sources: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return " | ".join(
            [
                f"Location: {self.location_name}",
                f"Market tier: {self.market_tier}",
                f"Demographics: {self.demographics}",
                f"Competition: {self.competition}",
            ]
        )


@dataclass
class DraftCopy:
    headline: str
    body: str
    cta: str

    @property
    def full_text(self) -> str:
        return "\n".join([self.headline.strip(), self.body.strip(), self.cta.strip()]).strip()


@dataclass
class Critique:
    passed: bool
    scores: dict[str, int]
    feedback: str
    rationale: list[str] = field(default_factory=list)


@dataclass
class GenerationRequest:
    corporate_prompt: str
    zip_codes: list[str]
    brand_guardrails: str = ""
    target_variants: int = 50


@dataclass
class TraceEvent:
    step: str
    timestamp: str
    payload: dict[str, object]

    @classmethod
    def create(cls, step: str, payload: dict[str, object]) -> "TraceEvent":
        return cls(
            step=step,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=payload,
        )


@dataclass
class AdVariant:
    request_id: str
    zip_code: str
    status: Literal["passed", "failed", "timeout", "error"]
    attempts: int
    latency_ms: int
    context: LocalContext | None = None
    draft: DraftCopy | None = None
    critique: Critique | None = None
    trace_id: str | None = None
    trace_path: str | None = None
    trace_events: list | None = None
    error: str | None = None


@dataclass
class BatchResult:
    request_id: str
    generated_at: str
    duration_ms: int
    requested_variants: int
    successful_variants: int
    pass_rate: float
    variants: list[AdVariant]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
