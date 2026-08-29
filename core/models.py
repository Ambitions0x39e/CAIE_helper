from __future__ import annotations

import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, computed_field, field_validator, model_validator


class PaperType(StrEnum):
    """Paper component type — determines parser, prompt, and UI workflow."""
    MATH = "math"
    MCQ = "mcq"


class MistakeRecord(BaseModel):
    """One question a grading run did not award full marks for.

    Append-only: re-grading a paper writes a second set of rows rather than
    replacing the first, and a question that later scores full marks does not
    remove its earlier row (see the design doc's Edge Cases).
    """

    model_config = {"strict": True}

    paper_id: str
    question_id: str
    topic_id: str | None = None
    topic_name: str | None = None
    score: float
    max_score: float
    comment: str = ""
    timestamp: datetime.datetime

    @field_validator("paper_id", "question_id")
    @classmethod
    def ids_must_be_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("paper_id and question_id cannot be empty")
        return v

    @field_validator("score", "max_score", mode="before")
    @classmethod
    def marks_must_be_non_negative(cls, v: object) -> object:
        if not isinstance(v, (int, float)):
            raise TypeError(f"Expected a number, got {type(v).__name__}")
        if v < 0:
            raise ValueError("Mark values cannot be negative")
        return float(v)

    @model_validator(mode="after")
    def score_must_not_exceed_max(self) -> MistakeRecord:
        if self.score > self.max_score:
            raise ValueError(
                f"score ({self.score}) cannot exceed max_score ({self.max_score})"
            )
        return self


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
