"""POST /api/v1/candidates/import end to end against Postgres."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.db import app_engine
from app.importer.pipeline import EXPECTED_HEADER
from app.main import create_app
from tests.helpers import insert_candidates

ADMIN = {"X-Recruiter-Id": "R-101"}
EXPECTED_REJECTED = [35, 36, 37, 38, 42, 43, 47, 49, 53, 54]
HEADER = ",".join(EXPECTED_HEADER)


@pytest.fixture
def client(db):
    with TestClient(create_app()) as client:
        yield client


def upload(client, data: bytes, headers=ADMIN):
    return client.post(
        "/api/v1/candidates/import",
        files={"file": ("candidates.csv", data, "text/csv")},
        headers=headers,
    )


def scalar(db, sql: str, **params):
    with db.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def test_full_import_report(client, db, raw_csv):
    response = upload(client, raw_csv)

    assert response.status_code == 200
    report = response.json()
    assert (report["imported"], report["merged"]) == (40, 3)
    assert [r["row"] for r in report["rejected"]] == EXPECTED_REJECTED
    assert report["warnings"] == []
    assert {(m["row"], m["candidate_id"], m["kept_row"]) for m in report["merges"]} == {
        (2, "C-1001", 33),
        (5, "C-1004", 32),
        (17, "C-1016", 34),
    }
    assert scalar(db, "SELECT count(*) FROM candidates") == 40


def test_every_row_is_accounted_for(client, raw_csv):
    for _ in range(2):
        report = upload(client, raw_csv).json()
        assert report["imported"] + report["merged"] + len(report["rejected"]) == 53


def test_reimport_is_idempotent(client, db, raw_csv):
    upload(client, raw_csv)
    report = upload(client, raw_csv).json()

    # 3 in-file duplicates + 40 survivors that now update existing records.
    assert (report["imported"], report["merged"]) == (0, 43)
    assert len(report["rejected"]) == 10
    assert scalar(db, "SELECT count(*) FROM candidates") == 40
    amara = [m for m in report["merges"] if m["kept_row"] == 34 and m["row"] is None]
    assert amara == [{"row": None, "candidate_id": "C-1032", "kept_row": 34}]


def test_dedup_last_wins_in_db(client, db, raw_csv):
    upload(client, raw_csv)
    with db.connect() as conn:
        amara = conn.execute(
            text(
                "SELECT candidate_id, first_name, salary_expectation FROM candidates"
                " WHERE email = 'amara.diallo@gmail.com'"
            )
        ).one()
        gone = conn.execute(
            text("SELECT count(*) FROM candidates WHERE candidate_id IN ('C-1001', 'C-1016')")
        ).scalar()
    assert tuple(amara) == ("C-1032", "A.", 110000)
    assert gone == 0
    assert scalar(db, "SELECT count(*) FROM candidates WHERE candidate_id = 'C-1004'") == 1


def test_invalid_email_rejected(client, db, raw_csv):
    report = upload(client, raw_csv).json()
    reasons = {r["row"]: r["reason"] for r in report["rejected"]}

    assert reasons[35] == "email: invalid address 'marcus.reed[at]gmail.com'"
    assert reasons[36] == "email: invalid address 'tina.holloway.gmail.com'"
    assert reasons[37] == "email: required"
    assert scalar(db, "SELECT count(*) FROM candidates WHERE candidate_id IN ('C-1033','C-1034','C-1035')") == 0


def test_injection_rows(client, db, raw_csv):
    report = upload(client, raw_csv).json()
    reasons = {r["row"]: r["reason"] for r in report["rejected"]}

    assert reasons[38].startswith("last_name: contains characters")
    assert scalar(db, "SELECT to_regclass('public.candidates') IS NOT NULL") is True
    assert scalar(db, "SELECT count(*) FROM candidates") == 40
    assert scalar(db, "SELECT notes FROM candidates WHERE candidate_id = 'C-1037'") == "' OR '1'='1"


def test_injection_in_free_text_fields_is_stored_literally(client, db):
    payload = "x'); DROP TABLE candidates;--"
    row = f'C-9001,Ana,Lopez,ana@example.com,,US-W,"{payload}",,2026-07-01,Active,"{payload}","{payload}"'

    report = upload(client, f"{HEADER}\n{row}\n".encode()).json()

    assert report["imported"] == 1
    with db.connect() as conn:
        stored = conn.execute(
            text("SELECT desired_role, source, notes FROM candidates WHERE candidate_id = 'C-9001'")
        ).one()
    assert tuple(stored) == (payload, payload, payload)
    assert scalar(db, "SELECT count(*) FROM recruiters") == 5


@pytest.mark.parametrize("headers", [{"X-Recruiter-Id": "R-102"}, {"X-Recruiter-Id": "R-999"}, {}])
def test_import_requires_admin(client, db, raw_csv, headers):
    response = upload(client, raw_csv, headers=headers)

    assert response.status_code == 403
    assert scalar(db, "SELECT count(*) FROM candidates") == 0


@pytest.mark.parametrize(
    "data, detail",
    [
        (b"id,name\nC-1,x\n", "unexpected header"),
        (HEADER.encode() + b"\n\xff\xfe\x00\n", "file is not valid UTF-8"),
        (b"", "file is empty"),
    ],
)
def test_bad_file_400(client, data, detail):
    response = upload(client, data)

    assert response.status_code == 400
    assert response.json()["detail"].startswith(detail)


def test_oversized_file_413(client):
    response = upload(client, HEADER.encode() + b"\n" + b"x" * (5 * 1024 * 1024))

    assert response.status_code == 413


def test_writes_are_batched(client, raw_csv):
    statements = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(app_engine(), "before_cursor_execute", record)
    try:
        upload(client, raw_csv)
    finally:
        event.remove(app_engine(), "before_cursor_execute", record)

    inserts = [s for s in statements if s.lstrip().upper().startswith("INSERT INTO CANDIDATES")]
    assert len(inserts) == 1


def test_db_collision_rejected(client, db):
    insert_candidates(db, {"candidate_id": "C-2000", "email": "a@example.com", "region_code": "US-W"})
    row = "C-2000,Ana,Lopez,b@example.com,,US-W,QA,,2026-07-01,Active,,"

    report = upload(client, f"{HEADER}\n{row}\n".encode()).json()

    assert report["imported"] == 0
    assert report["rejected"] == [
        {
            "row": 2,
            "candidate_id": "C-2000",
            "reason": "candidate_id: C-2000 already used by an existing candidate with a different email",
        }
    ]
    assert scalar(db, "SELECT email FROM candidates WHERE candidate_id = 'C-2000'") == "a@example.com"


def test_unicode_round_trip(client, db, raw_csv):
    upload(client, raw_csv)
    assert scalar(db, "SELECT first_name || ' ' || last_name FROM candidates WHERE candidate_id = 'C-1008'") == "Nguyễn Thị Hoa"
