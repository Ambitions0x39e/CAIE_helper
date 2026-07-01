from __future__ import annotations

import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, computed_field, field_validator, model_validator


class PaperType(StrEnum):
    """Paper component type — determines parser, prompt, and UI workflow."""
    MATH = "math"
    MCQ = "mcq"


SUBJECT_PAPER_TYPES: dict[str, PaperType] = {
    "9709": PaperType.MATH,
    "9231": PaperType.MATH,
    # MCQ (Paper 1) subjects
    "9702": PaperType.MCQ,  # Physics
    "9701": PaperType.MCQ,  # Chemistry
    "9700": PaperType.MCQ,  # Biology
    "9696": PaperType.MCQ,  # Geography
}


def detect_paper_type(paper_id: str) -> PaperType | None:
    """Resolve a paper_id (e.g. '9231_w22_qp_41') to its PaperType, or None."""
    subject = paper_id.split("_")[0] if "_" in paper_id else paper_id[:4]
    return SUBJECT_PAPER_TYPES.get(subject)


class PaperRecord(BaseModel):
    """Represents a single past paper entry in the tracker."""

    model_config = {"strict": True}

    paper_id: str
    status: Literal["Pending", "Completed"] = "Pending"
    qp_path: str = ""
    ms_path: str = ""
    score_raw: float | None = None
    score_total: float | None = None
    sent_to_gn: bool = False
    timestamp: datetime.datetime | None = None

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------

    @computed_field  # type: ignore[prop-decorator]
    @property
    def percentage(self) -> float | None:
        if (
            self.score_raw is not None
            and self.score_total is not None
            and self.score_total > 0
        ):
            return round((self.score_raw / self.score_total) * 100, 2)
        return None

    # ------------------------------------------------------------------
    # Field validators
    # ------------------------------------------------------------------

    @field_validator("paper_id")
    @classmethod
    def paper_id_must_be_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("paper_id cannot be empty or whitespace")
        return v

    @field_validator("score_raw", "score_total", mode="before")
    @classmethod
    def scores_must_be_non_negative(cls, v: object) -> object:
        if v is None:
            return v
        if not isinstance(v, (int, float)):
            raise TypeError(f"Expected a number, got {type(v).__name__}")
        if v < 0:
            raise ValueError("Score values cannot be negative")
        return float(v)

    @field_validator("qp_path", "ms_path")
    @classmethod
    def paths_strip(cls, v: str) -> str:
        return v.strip()

    # ------------------------------------------------------------------
    # Cross-field validators
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def completed_requires_scores(self) -> PaperRecord:
        """A Completed record must have both score fields populated."""
        if self.status == "Completed" and (
            self.score_raw is None or self.score_total is None
        ):
            raise ValueError(
                "status='Completed' requires both score_raw and score_total"
            )
        return self

    @model_validator(mode="after")
    def raw_must_not_exceed_total(self) -> PaperRecord:
        if (
            self.score_raw is not None
            and self.score_total is not None
            and self.score_raw > self.score_total
        ):
            raise ValueError(
                f"score_raw ({self.score_raw}) cannot exceed "
                f"score_total ({self.score_total})"
            )
        return self
