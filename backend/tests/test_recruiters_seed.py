import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import get_settings
from app.db import app_engine
from app.main import create_app
from app.recruiters import Recruiter, RosterError, get_recruiter, load_roster

HEADER = "recruiter_id,full_name,email,role,assigned_regions\n"


def write_roster(tmp_path, *lines: str):
    path = tmp_path / "recruiters.csv"
    path.write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_real_roster():
    roster = {r.recruiter_id: r for r in load_roster(get_settings().recruiters_csv)}
    assert sorted(roster) == ["R-101", "R-102", "R-103", "R-104", "R-105"]
    assert roster["R-101"] == Recruiter("R-101", "Dana Whitmore", True, ())
    assert roster["R-102"].regions == ("US-MW", "US-NE")
    assert roster["R-103"].regions == ("PH-MNL", "CO-BOG")
    assert not roster["R-105"].is_admin


@pytest.mark.parametrize(
    "line, message",
    [
        ("R-1,A,a@x.com,admin,*|US-MW", "'*' must be the only region"),
        ("R-1,A,a@x.com,recruiter,*", "'*' requires role admin"),
        ("R-1,A,a@x.com,admin,US-MW", "role admin requires regions '*'"),
        ("R-1,A,a@x.com,recruiter,ZZ-99", "unknown region 'ZZ-99'"),
        ("R-1,A,a@x.com,recruiter,", "no regions"),
        ("R-1,A,a@x.com,boss,US-MW", "unknown role 'boss'"),
    ],
)
def test_bad_roster_fails_loudly(tmp_path, line, message):
    with pytest.raises(RosterError, match=message):
        load_roster(write_roster(tmp_path, line))


def test_duplicate_recruiter_id(tmp_path):
    path = write_roster(tmp_path, "R-1,A,a@x.com,recruiter,US-W", "R-1,B,b@x.com,recruiter,US-W")
    with pytest.raises(RosterError, match="duplicate recruiter_id 'R-1'"):
        load_roster(path)


def test_startup_migrates_and_reseeds(db):
    with db.begin() as conn:
        conn.execute(text("DELETE FROM recruiter_regions WHERE recruiter_id = 'R-105'"))
    with TestClient(create_app()):
        pass
    with app_engine().connect() as conn:
        assert get_recruiter(conn, "R-105").regions == ("US-NE",)


def test_get_recruiter_from_seeded_db(db):
    with app_engine().connect() as conn:
        assert get_recruiter(conn, "R-104") == Recruiter(
            "R-104", "Jordan Blake", False, ("US-SE", "US-W")
        )
        assert get_recruiter(conn, "R-101").is_admin
        assert get_recruiter(conn, "R-999") is None
