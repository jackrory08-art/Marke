"""Output schemas for the model. Length/range limits are enforced by trimming
validators (not schema constraints) so one long field never fails a whole call,
and the schema sent to the provider stays simple."""

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, field_validator


def _trim(n: int):
    return BeforeValidator(lambda v: v[:n] if isinstance(v, str) else v)


def _clamp01(v):
    try:
        return min(1.0, max(0.0, float(v)))
    except (TypeError, ValueError):
        return v


DifferenceKind = Literal[
    "date", "threshold", "wording", "resolution_source",
    "inverse_polarity", "scope", "missing_rules", "other",
]


class Difference(BaseModel):
    kind: DifferenceKind
    detail: Annotated[str, _trim(300)]


class MatchVerdict(BaseModel):
    verdict: Literal["identical", "equivalent_with_caveats", "different"]
    confidence: Annotated[float, BeforeValidator(_clamp01)]
    differences: list[Difference]
    short_reason: Annotated[str, _trim(280)]

    @field_validator("differences", mode="before")
    @classmethod
    def _limit_differences(cls, v):
        return v[:8] if isinstance(v, list) else v
