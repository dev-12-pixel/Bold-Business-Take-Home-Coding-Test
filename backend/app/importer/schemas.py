from pydantic import BaseModel


class RejectedRow(BaseModel):
    row: int
    candidate_id: str | None
    reason: str


class WarningRow(BaseModel):
    row: int
    candidate_id: str
    message: str


class MergedRow(BaseModel):
    row: int | None
    candidate_id: str
    kept_row: int


class ImportReport(BaseModel):
    """Brief's {imported, merged, rejected} plus warnings and merge detail (D16, D23)."""

    imported: int
    merged: int
    rejected: list[RejectedRow]
    warnings: list[WarningRow]
    merges: list[MergedRow]
