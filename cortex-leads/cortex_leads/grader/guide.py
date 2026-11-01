"""What a piece of work is graded on (WP33). The teacher's words, kept as data: criteria with points that add up to the maximum
and, if there is one, the answer key. The grader sees nothing else about how to score, so a model cannot grade on a rubric it
made up, and a student's text cannot change what the criteria are."""
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from cortex_leads.core.errors import CortexError
from cortex_leads.skills.loader import load_yaml

SLUG = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
TOLERANCE = 0.01


class Criterion(BaseModel):
    id: str
    label: str = Field(min_length=1, max_length=80)
    points: float = Field(gt=0, le=1000)
    descriptor: str = Field(default="", max_length=400)  # what earns the points

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG.match(v):
            raise ValueError("criterion id must be a lowercase slug")
        return v


class Guide(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    max_points: float = Field(gt=0, le=1000)
    criteria: list[Criterion] = Field(min_length=1, max_length=12)
    answer_key: str | None = Field(default=None, max_length=8000)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")  # of a spoken answer (vi, en…); None: detect
    check_prompt: str | None = Field(default=None, max_length=4000)  # the teacher's instructions on how to check the work against the answer key

    @model_validator(mode="after")
    def _adds_up(self) -> "Guide":
        if len({c.id for c in self.criteria}) != len(self.criteria):
            raise ValueError("criterion ids must be unique")
        if abs(sum(c.points for c in self.criteria) - self.max_points) > TOLERANCE:
            raise ValueError(f"criteria points add up to {sum(c.points for c in self.criteria)}, not max_points {self.max_points}")
        return self

    def criteria_json(self) -> list[dict[str, Any]]:
        return [c.model_dump() for c in self.criteria]


class GuideError(CortexError):
    """A grading guide that cannot be used; the message says what to fix."""


def parse_guide(data: Any) -> Guide:
    try:
        return Guide(**data)
    except (ValidationError, TypeError) as e:
        raise GuideError(str(e)) from e


def load_guide_file(path: Path) -> Guide:
    return parse_guide(load_yaml(path.read_text(encoding="utf-8")))


def guide_of(row: Any) -> Guide:
    """From an `assignment` row. One with no criteria has no guide: GuideError, and nothing is graded."""
    try:
        return Guide(title=row.title, max_points=float(row.max_points or 0), criteria=row.criteria or [], answer_key=row.answer_key,
                     language=row.language, check_prompt=row.check_prompt)
    except ValidationError as e:
        raise GuideError(str(e)) from e
