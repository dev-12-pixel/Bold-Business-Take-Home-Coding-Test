"""Row-level security is the only scoping mechanism (D18). These tests talk to
Postgres directly as the app role, without any API code in between."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.config import get_settings
from app.db import app_engine, scoped
from tests.helpers import insert_candidates

REGIONS = ["US-MW", "US-NE", "US-SE", "US-W", "PH-MNL", "CO-BOG"]


@pytest.fixture
def one_per_region(db):
    insert_candidates(
        db,
        *[
            {"candidate_id": f"C-{9000 + i}", "email": f"c{i}@example.com", "region_code": r}
            for i, r in enumerate(REGIONS)
        ],
    )


def visible_regions(conn) -> set[str]:
    return set(conn.execute(text("SELECT region_code FROM candidates")).scalars())


def test_app_role_is_not_superuser(db):
    with app_engine().connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
    assert tuple(row) == (False, False)


def test_app_role_without_setting_sees_nothing(one_per_region):
    with app_engine().connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM candidates")).scalar() == 0


def test_caleb_sees_only_his_regions(one_per_region):
    with scoped("R-102") as conn:
        assert visible_regions(conn) == {"US-MW", "US-NE"}


def test_marisol_sees_only_her_regions(one_per_region):
    with scoped("R-103") as conn:
        assert visible_regions(conn) == {"PH-MNL", "CO-BOG"}


def test_dana_sees_all(one_per_region):
    with scoped("R-101") as conn:
        assert visible_regions(conn) == set(REGIONS)


def test_unknown_id_sees_nothing(one_per_region):
    with scoped("R-999") as conn:
        assert visible_regions(conn) == set()


def test_scope_does_not_leak_across_transactions(one_per_region):
    engine = create_engine(get_settings().app_url, pool_size=1, max_overflow=0)
    try:
        with scoped("R-101", engine) as conn:
            assert len(visible_regions(conn)) == 6
        with engine.connect() as conn:
            assert visible_regions(conn) == set()
    finally:
        engine.dispose()


def test_app_role_cannot_insert_outside_scope(db):
    with pytest.raises(DBAPIError, match="row-level security"):
        with scoped("R-102") as conn:
            conn.execute(
                text(
                    "INSERT INTO candidates (candidate_id, first_name, last_name, email,"
                    " region_code, applied_date, status) VALUES ('C-9100', 'A', 'B',"
                    " 'x@example.com', 'PH-MNL', '2026-07-01', 'active')"
                )
            )


def test_app_role_cannot_delete(one_per_region):
    with pytest.raises(DBAPIError, match="permission denied"):
        with scoped("R-101") as conn:
            conn.execute(text("DELETE FROM candidates"))
