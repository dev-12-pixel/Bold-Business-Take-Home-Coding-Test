"""Pure import pipeline: bytes -> rows -> validated models -> deduplicated plan.

No database access here; repository.apply_plan writes the result.
Row numbers are spreadsheet rows: the header is row 1 (D1).
"""
import csv
import io
from dataclasses import dataclass

from pydantic import ValidationError

from app.importer.models import CandidateIn
from app.importer.normalize import parse_salary

EXPECTED_HEADER = (
    "candidate_id",
    "first_name",
    "last_name",
    "email",
    "phone",
    "region_code",
    "desired_role",
    "salary_expectation",
    "applied_date",
    "status",
    "source",
    "notes",
)


class FileError(Exception):
    """The upload as a whole is unusable (encoding, header, empty)."""


@dataclass
class RawRow:
    row: int
    fields: list[str]


@dataclass
class Rejection:
    row: int
    candidate_id: str | None
    reason: str


@dataclass
class ImportWarning:
    row: int
    candidate_id: str
    message: str


@dataclass
class Merge:
    """`row`/`candidate_id` identify the superseded record, `kept_row` the winner (D23).
    `row` is None when the superseded record was already in the database."""

    row: int | None
    candidate_id: str
    kept_row: int


@dataclass
class ImportPlan:
    survivors: list[tuple[int, CandidateIn]]
    rejected: list[Rejection]
    warnings: list[ImportWarning]
    merges: list[Merge]


def parse_csv(data: bytes) -> list[RawRow]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise FileError("file is not valid UTF-8") from None
    records = csv.reader(io.StringIO(text, newline=""))
    header = next(records, None)
    if header is None:
        raise FileError("file is empty")
    if tuple(h.strip() for h in header) != EXPECTED_HEADER:
        raise FileError(f"unexpected header: expected {','.join(EXPECTED_HEADER)}")
    return [RawRow(row, fields) for row, fields in enumerate(records, start=2) if fields]


def _validate(raw: RawRow) -> tuple[CandidateIn | None, str | None, str | None]:
    """Return (model, salary_warning, rejection_reason)."""
    if len(raw.fields) != len(EXPECTED_HEADER):
        return None, None, f"expected {len(EXPECTED_HEADER)} fields, got {len(raw.fields)}"
    values = dict(zip(EXPECTED_HEADER, raw.fields))
    salary, warning = parse_salary(values["salary_expectation"])
    try:
        model = CandidateIn.model_validate({**values, "salary_expectation": salary})
    except ValidationError as exc:
        reasons = [
            f"{err['loc'][0]}: {err['msg'].removeprefix('Value error, ')}" for err in exc.errors()
        ]
        return None, None, "; ".join(reasons)
    return model, warning, None


def build_plan(rows: list[RawRow]) -> ImportPlan:
    rejected: list[Rejection] = []
    warnings: dict[int, ImportWarning] = {}
    merges: list[Merge] = []
    id_owner: dict[str, tuple[int, str]] = {}  # candidate_id -> (row, email), first claimant (D27)
    by_email: dict[str, tuple[int, CandidateIn]] = {}  # last occurrence wins (D2)

    for raw in rows:
        model, warning, reason = _validate(raw)
        if model is None:
            candidate_id = raw.fields[0].strip() if raw.fields and raw.fields[0].strip() else None
            rejected.append(Rejection(raw.row, candidate_id, reason))
            continue

        owner = id_owner.get(model.candidate_id)
        if owner and owner[1] != model.email:
            rejected.append(
                Rejection(
                    raw.row,
                    model.candidate_id,
                    f"candidate_id: {model.candidate_id} already used by row {owner[0]} "
                    "with a different email",
                )
            )
            continue
        id_owner.setdefault(model.candidate_id, (raw.row, model.email))

        if model.email in by_email:
            previous_row, previous = by_email[model.email]
            merges.append(Merge(previous_row, previous.candidate_id, raw.row))
            warnings.pop(previous_row, None)
        by_email[model.email] = (raw.row, model)
        if warning:
            warnings[raw.row] = ImportWarning(raw.row, model.candidate_id, warning)

    return ImportPlan(
        survivors=sorted(by_email.values(), key=lambda item: item[0]),
        rejected=rejected,
        warnings=sorted(warnings.values(), key=lambda w: w.row),
        merges=merges,
    )
