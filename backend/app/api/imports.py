from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.api.deps import current_admin
from app.db import scoped
from app.importer.pipeline import FileError, build_plan, parse_csv
from app.importer.repository import apply_plan
from app.importer.schemas import ImportReport
from app.recruiters import Recruiter

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

router = APIRouter()


@router.post("/api/v1/candidates/import", response_model=ImportReport)
async def import_candidates(
    file: UploadFile,
    admin: Annotated[Recruiter, Depends(current_admin)],
) -> ImportReport:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file larger than 5 MB")
    try:
        plan = build_plan(parse_csv(data))
    except FileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    with scoped(admin.recruiter_id) as conn:
        return apply_plan(conn, plan)
