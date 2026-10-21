import os
from pathlib import Path

# Must be set before anything reads settings: tests never touch the dev database.
os.environ["TECHFORCE_DB"] = "techforce_test"

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import migrate, owner_engine  # noqa: E402
from app.recruiters import seed_recruiters  # noqa: E402

CANDIDATES_CSV = Path("/data/candidates_import.csv")


@pytest.fixture(scope="session")
def raw_csv() -> bytes:
    return CANDIDATES_CSV.read_bytes()


@pytest.fixture(scope="session")
def _schema():
    engine = owner_engine()
    migrate(engine)
    seed_recruiters(engine, get_settings().recruiters_csv)
    return engine


@pytest.fixture
def db(_schema):
    """Owner engine on a migrated, seeded test database with no candidates."""
    with _schema.begin() as conn:
        conn.execute(text("TRUNCATE candidates RESTART IDENTITY"))
    return _schema
