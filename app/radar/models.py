from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

ROLES = ("participants", "officials", "related_persons")


class Source(BaseModel):
    file_role: str
    filename: str
    sheet: str | None
    row: int


@dataclass
class Record:
    values: dict[str, str]
    source: Source


class Diagnostic(BaseModel):
    code: str
    file_role: str
    field: str | None = None
    message: str
    row: int | None = None
    rows: list[int] | None = None


class InputError(ValueError):
    def __init__(self, errors: list[Diagnostic]):
        self.errors = errors
        super().__init__("; ".join(error.message for error in errors))


class Match(BaseModel):
    rule_id: str
    points: int
    left_field: str
    right_field: str
    left_raw: str
    right_raw: str
    left_normalized: str
    right_normalized: str
    similarity: float | None = None


class Alert(BaseModel):
    tender_id: str
    participant: dict[str, str]
    official: dict[str, str]
    related_person: dict[str, str]
    score: int
    level: Literal["high", "medium", "low"]
    sources: list[Source]
    matches: list[Match]


class Summary(BaseModel):
    rows_read: dict[str, int]
    rows_skipped: dict[str, int]
    alert_count: int


class CheckResult(BaseModel):
    summary: Summary
    alerts: list[Alert]
    warnings: list[Diagnostic]
