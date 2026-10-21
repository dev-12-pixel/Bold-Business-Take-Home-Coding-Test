from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import Path

from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import URL

from app.config import get_settings

SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


@cache
def _engine(url: URL) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def owner_engine() -> Engine:
    return _engine(get_settings().owner_url)


def app_engine() -> Engine:
    return _engine(get_settings().app_url)


def migrate(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(SCHEMA)


@contextmanager
def scoped(recruiter_id: str, engine: Engine | None = None) -> Iterator[Connection]:
    """A transaction as the app role in which RLS sees `recruiter_id`.

    set_config(..., true) is transaction-local, so the setting cannot leak to
    the next user of a pooled connection.
    """
    with (engine or app_engine()).begin() as conn:
        conn.execute(
            text("SELECT set_config('app.recruiter_id', :recruiter_id, true)"),
            {"recruiter_id": recruiter_id},
        )
        yield conn
