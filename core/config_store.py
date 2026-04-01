from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, field_validator

# Path relative to this file: repo_root/core/../data/syllabus_config.json
_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "data" / "syllabus_config.json"


# ---------------------------------------------------------------------------
# Pydantic models for config structure
# ---------------------------------------------------------------------------


class PaperTypeConfig(BaseModel):
    """Metadata for a single paper type digit (e.g. '1' → 'Multiple Choice')."""

    model_config = {"strict": True}

    digit: str
    name: str

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
        { "9702": { "name": "Physics", "paper_types": { "1": "MCQ", "2": "AS Structured" } } }
        """
        entries = self.load_all()
        return {
            e.syllabus_id: {
                "name": e.name,
                "paper_types": e.paper_types_as_dict(),
            }
            for e in entries
        }

    def save_all(self, entries: list[SyllabusConfig]) -> None:
        """Overwrite the JSON file with the given entries."""
        data = [e.model_dump() for e in entries]
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def upsert(self, entry: SyllabusConfig) -> None:
        """Insert or replace a syllabus entry by syllabus_id."""
        entries = self.load_all()
        for i, e in enumerate(entries):
            if e.syllabus_id == entry.syllabus_id:
                entries[i] = entry
                self.save_all(entries)
                return
        entries.append(entry)
        self.save_all(entries)

    def delete(self, syllabus_id: str) -> None:
        """Remove a syllabus entry by syllabus_id."""
        entries = self.load_all()
        filtered = [e for e in entries if e.syllabus_id != syllabus_id]
        if len(filtered) == len(entries):
            raise KeyError(f"syllabus_id '{syllabus_id}' not found in config")
        self.save_all(filtered)