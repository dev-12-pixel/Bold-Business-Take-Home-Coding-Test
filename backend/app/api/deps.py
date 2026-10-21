from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.db import app_engine
from app.recruiters import Recruiter, get_recruiter


def current_recruiter(
    x_recruiter_id: Annotated[str | None, Header(alias="X-Recruiter-Id")] = None,
) -> Recruiter:
    """Missing or unknown recruiter -> 403 (D21). Identity only; scoping is RLS's job."""
    recruiter = None
    if x_recruiter_id:
        with app_engine().connect() as conn:
            recruiter = get_recruiter(conn, x_recruiter_id.strip())
    if recruiter is None:
        raise HTTPException(status_code=403, detail="unknown recruiter")
    return recruiter


def current_admin(recruiter: Annotated[Recruiter, Depends(current_recruiter)]) -> Recruiter:
    if not recruiter.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    return recruiter
