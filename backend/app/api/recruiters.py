from fastapi import APIRouter
from pydantic import BaseModel

from app.db import app_engine
from app.recruiters import list_recruiters

router = APIRouter()


class RecruiterOut(BaseModel):
    recruiter_id: str
    full_name: str
    is_admin: bool
    regions: list[str]


@router.get("/api/v1/recruiters", response_model=list[RecruiterOut])
def recruiters() -> list[RecruiterOut]:
    """The roster for the UI's switcher. Unauthenticated: it holds no candidate data."""
    with app_engine().connect() as conn:
        return [
            RecruiterOut(
                recruiter_id=r.recruiter_id,
                full_name=r.full_name,
                is_admin=r.is_admin,
                regions=list(r.regions),
            )
            for r in list_recruiters(conn)
        ]
