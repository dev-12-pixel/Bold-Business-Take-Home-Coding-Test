from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.types import Message

from app.api.deps import current_admin
from app.db import scoped
from app.importer.pipeline import FileError, RawRow, parse_csv
from app.importer.repository import import_rows
from app.importer.schemas import ImportReport
from app.recruiters import Recruiter

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
# Room for the multipart envelope around a file of MAX_UPLOAD_BYTES.
MAX_BODY_BYTES = MAX_UPLOAD_BYTES + 64 * 1024

router = APIRouter()

_TOO_LARGE = HTTPException(status_code=413, detail="file larger than 5 MB")

_UPLOAD_SCHEMA = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}


def _capped(request: Request) -> Request:
    """The same request, but reading more than MAX_BODY_BYTES raises 413 mid-stream."""
    received = 0

    async def receive() -> Message:
        nonlocal received
        message = await request.receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > MAX_BODY_BYTES:
                raise _TOO_LARGE
        return message

    return Request(request.scope, receive)


# The body is taken from `request`, not declared as an UploadFile parameter: FastAPI
# reads declared bodies before running dependencies, which would let anyone stream
# an unlimited upload before the admin check refuses them.
@router.post("/api/v1/candidates/import", response_model=ImportReport, openapi_extra=_UPLOAD_SCHEMA)
async def import_candidates(
    request: Request,
    admin: Annotated[Recruiter, Depends(current_admin)],
) -> ImportReport:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _TOO_LARGE
    async with _capped(request).form(max_files=1, max_fields=0) as form:
        file = form.get("file")
        if not isinstance(file, UploadFile):
            raise HTTPException(status_code=422, detail="multipart field 'file' is required")
        data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise _TOO_LARGE
    try:
        rows = parse_csv(data)
    except FileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    # Blocking DB work goes to the threadpool so an import doesn't stall the event loop.
    return await run_in_threadpool(_write, admin.recruiter_id, rows)


def _write(recruiter_id: str, rows: list[RawRow]) -> ImportReport:
    with scoped(recruiter_id) as conn:
        return import_rows(conn, rows)
