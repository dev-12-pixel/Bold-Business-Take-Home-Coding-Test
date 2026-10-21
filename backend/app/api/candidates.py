"""Scoped read API (D18, D21, D22, D24, D25).

There is deliberately no region filter in this module: every query runs in
db.scoped(), and Postgres row-level security decides which rows exist.
"""
import unicodedata
from datetime import date
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, or_, select

from app.api.deps import current_recruiter
from app.db import scoped
from app.importer.normalize import STATUSES
from app.recruiters import Recruiter
from app.tables import candidates

router = APIRouter()

Status = Enum("Status", {s: s for s in STATUSES}, type=str)


class CandidateOut(BaseModel):
    candidate_id: str
    first_name: str
    last_name: str
    email: str
    region_code: str
    desired_role: str | None
    status: str
    applied_date: date


class CandidatePage(BaseModel):
    items: list[CandidateOut]
    total: int
    page: int
    page_size: int


_COLUMNS = [candidates.c[name] for name in CandidateOut.model_fields]
_SEARCHABLE = [
    candidates.c.first_name,
    candidates.c.last_name,
    candidates.c.first_name + " " + candidates.c.last_name,
    candidates.c.email,
    candidates.c.desired_role,
]


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtered(query: Select, search: str | None, status: Status | None) -> Select:
    term = unicodedata.normalize("NFC", search or "").strip()
    if term:
        pattern = f"%{_escape_like(term)}%"
        query = query.where(or_(*(col.ilike(pattern, escape="\\") for col in _SEARCHABLE)))
    if status is not None:
        query = query.where(candidates.c.status == status.value)
    return query


@router.get("/api/v1/candidates", response_model=CandidatePage)
def list_candidates(
    recruiter: Annotated[Recruiter, Depends(current_recruiter)],
    search: str | None = None,
    status: Status | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> CandidatePage:
    with scoped(recruiter.recruiter_id) as conn:
        total = conn.execute(
            _filtered(select(func.count()).select_from(candidates), search, status)
        ).scalar_one()
        rows = conn.execute(
            _filtered(select(*_COLUMNS), search, status)
            .order_by(candidates.c.applied_date.desc(), candidates.c.candidate_id)
            .limit(page_size)
            .offset((page - 1) * page_size)
        ).mappings()
        items = [CandidateOut.model_validate(dict(row)) for row in rows]
    return CandidatePage(items=items, total=total, page=page, page_size=page_size)


@router.get("/api/v1/candidates/{candidate_id}", response_model=CandidateOut)
def get_candidate(
    candidate_id: str, recruiter: Annotated[Recruiter, Depends(current_recruiter)]
) -> CandidateOut:
    with scoped(recruiter.recruiter_id) as conn:
        row = (
            conn.execute(select(*_COLUMNS).where(candidates.c.candidate_id == candidate_id))
            .mappings()
            .one_or_none()
        )
    if row is None:
        # Out of scope and nonexistent look the same: existence is not leaked.
        raise HTTPException(status_code=404, detail="candidate not found")
    return CandidateOut.model_validate(dict(row))
