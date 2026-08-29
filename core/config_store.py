from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, field_validator

from core.models import PaperType

# Path relative to this file: repo_root/core/../data/syllabus_config.json
_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "data" / "syllabus_config.json"
_PAGE_CONFIG_PATH = _REPO_ROOT / "data" / "paper_page_config.json"


# ---------------------------------------------------------------------------
# Pydantic models for config structure
# ---------------------------------------------------------------------------


class PaperTypeConfig(BaseModel):
    """Metadata for a single paper type digit (e.g. '1' → 'Multiple Choice')."""

    model_config = {"strict": True}

    digit: str
    name: str
    #: Which grading path this paper takes, when it is known up front.
    #: ``mcq`` is the deterministic answer-key path; ``math`` is the
    #: VL-graded one, which despite the name suits any structured paper
    #: (Chemistry Paper 2, a practical write-up) — the enum is named after
    #: the first flow that used it. ``None`` means "not recorded", and the
    #: Mark tab leaves whatever the user picked alone.
    grading: PaperType | None = None

    @field_validator("digit")
    @classmethod
    def digit_must_be_single(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or len(v) != 1:
            raise ValueError(f"digit must be a single numeric character, got: {v!r}")
        return v

    @field_validator("name")
    @classmethod
    def name_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Paper type name cannot be empty")
        return v


class SyllabusConfig(BaseModel):
    """Metadata for a single syllabus."""

    model_config = {"strict": True}

    syllabus_id: str
    name: str
    paper_types: list[PaperTypeConfig] = []

    @field_validator("syllabus_id")
    @classmethod
    def syllabus_id_format(cls, v: str) -> str:
        v = v.strip()
        if len(v) != 4 or not v.isdigit():
            raise ValueError(
                f"syllabus_id must be exactly 4 digits, got: {v!r}"
            )
        return v

    @field_validator("name")
    @classmethod
    def name_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Syllabus name cannot be empty")
        return v

    def paper_types_as_dict(self) -> dict[str, str]:
        """Return paper_types as {digit: name} for easy lookup in visualizer."""
        return {pt.digit: pt.name for pt in self.paper_types}


# ---------------------------------------------------------------------------
# Config store
# ---------------------------------------------------------------------------

# Resolved config type: { syllabus_id: { "name": str, "paper_types": {digit: name} } }
SyllabusConfigDict = dict[str, dict[str, str | dict[str, str]]]


class ConfigStore:
    """
    Reads and writes syllabus/paper-type metadata.
    Defaults to data/syllabus_config.json inside the repo.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._path = config_path or _DEFAULT_CONFIG_PATH

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(self) -> list[SyllabusConfig]:
        """Load and validate all syllabus entries from JSON."""
        if not self._path.exists():
            return []
        raw = self._path.read_text(encoding="utf-8")
        try:
            data: list[dict[str, object]] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"syllabus_config.json is not valid JSON: {exc}") from exc

        return [SyllabusConfig.model_validate(entry, strict=False) for entry in data]

    def load_syllabus_config(self) -> SyllabusConfigDict:
        """
        Return a flat dict for easy lookup by visualizer:
        { "9702": { "name": "Physics", "paper_types": { "1": "MCQ" } } }
        """
        entries = self.load_all()
        return {
            e.syllabus_id: {
                "name": e.name,
                "paper_types": e.paper_types_as_dict(),
            }
            for e in entries
        }


# ---------------------------------------------------------------------------
# QP page skipping  (data/paper_page_config.json)
# ---------------------------------------------------------------------------


def qp_skip_pages(
    subject_id: str, component: str, config_path: Path | None = None
) -> set[int]:
    """0-indexed QP pages the segmenter must skip — cover, formula list, …

    Args:
        subject_id: 4-digit syllabus code (e.g. "9702").
        component:  Component string from the paper_id, e.g. "11", "21".
                    The first character is used as the prefix key.
        config_path: Override for the JSON config path (used in tests).

    Resolved from the component's own entry, then the subject's ``_default``,
    then the file's top-level ``default``, then ``{0}``.
    """
    path = config_path or _PAGE_CONFIG_PATH
    raw: dict[str, dict[str, object]] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc

    prefix = component[0] if component else ""
    subject: dict[str, object] = raw.get(subject_id, {})
    for entry in (
        subject.get(prefix, {}),
        subject.get("_default", {}),
        raw.get("default", {}),
    ):
        pages = entry.get("qp_skip_pages") if isinstance(entry, dict) else None
        if isinstance(pages, list):
            return {int(p) for p in pages}
    return {0}


# ---------------------------------------------------------------------------
# Which grading path a paper takes
# ---------------------------------------------------------------------------


def grading_type_for_paper(
    paper_id: str, config_path: Path | None = None
) -> PaperType | None:
    """``"9701_s25_qp_21"`` → the grading path recorded for that component.

    None when the subject or its component isn't recorded, which leaves the
    Mark tab's radio exactly where the user left it. Same component-prefix
    convention as :func:`get_paper_page_config`: the first digit of the
    component, so 21 / 22 / 23 all resolve to Paper 2.
    """
    parts = paper_id.split("_")
    if len(parts) < 4 or not parts[3][:1].isdigit():
        return None
    subject_id, digit = parts[0], parts[3][0]

    for entry in ConfigStore(config_path).load_all():
        if entry.syllabus_id != subject_id:
            continue
        for paper_type in entry.paper_types:
            if paper_type.digit == digit:
                return paper_type.grading
    return None
