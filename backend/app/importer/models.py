from datetime import date

from pydantic import BaseModel, field_validator

from app.importer.normalize import (
    clean_optional,
    normalize_candidate_id,
    normalize_email,
    normalize_name,
    normalize_region,
    normalize_status,
    parse_date,
)


class CandidateIn(BaseModel):
    """A valid, normalized candidate row. Fields are declared in CSV column order
    so validation errors come out in that order too."""

    candidate_id: str
    first_name: str
    last_name: str
    email: str
    phone: str | None
    region_code: str
    desired_role: str | None
    # Parsed by the pipeline with parse_salary, which never fails (D11).
    salary_expectation: int | None
    applied_date: date
    status: str
    source: str | None
    notes: str | None

    _candidate_id = field_validator("candidate_id", mode="before")(normalize_candidate_id)
    _names = field_validator("first_name", "last_name", mode="before")(normalize_name)
    _email = field_validator("email", mode="before")(normalize_email)
    _region = field_validator("region_code", mode="before")(normalize_region)
    _status = field_validator("status", mode="before")(normalize_status)
    _date = field_validator("applied_date", mode="before")(parse_date)
    _optional = field_validator("phone", "desired_role", "source", "notes", mode="before")(
        clean_optional
    )
