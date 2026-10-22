"""Recruiter roster: strict load from recruiters.csv and seeding (D17)."""
import csv
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection, Engine, text

from app.importer.normalize import REGIONS

ROSTER_HEADER = ("recruiter_id", "full_name", "email", "role", "assigned_regions")
ROLES = ("admin", "recruiter")


class RosterError(Exception):
    pass


@dataclass(frozen=True)
class Recruiter:
    recruiter_id: str
    full_name: str
    is_admin: bool
    regions: tuple[str, ...]  # empty for admins: they see every region


@dataclass(frozen=True)
class _RosterEntry:
    recruiter: Recruiter
    email: str


def _parse_entry(line: int, fields: list[str]) -> _RosterEntry:
    if len(fields) != len(ROSTER_HEADER):
        raise RosterError(f"line {line}: expected {len(ROSTER_HEADER)} fields, got {len(fields)}")
    recruiter_id, full_name, email, role, assigned = (f.strip() for f in fields)
    if not recruiter_id or not full_name:
        raise RosterError(f"line {line}: recruiter_id and full_name are required")
    if role not in ROLES:
        raise RosterError(f"line {line}: unknown role '{role}'")
    tokens = [t.strip() for t in assigned.split("|") if t.strip()]
    if not tokens:
        raise RosterError(f"line {line}: no regions")
    if "*" in tokens:
        if tokens != ["*"]:
            raise RosterError(f"line {line}: '*' must be the only region")
        if role != "admin":
            raise RosterError(f"line {line}: '*' requires role admin")
        return _RosterEntry(Recruiter(recruiter_id, full_name, True, ()), email)
    if role == "admin":
        raise RosterError(f"line {line}: role admin requires regions '*'")
    for token in tokens:
        # The roster is our own reference data: codes must already be canonical.
        if token not in REGIONS:
            raise RosterError(f"line {line}: unknown region '{token}'")
    return _RosterEntry(Recruiter(recruiter_id, full_name, False, tuple(tokens)), email)


def _load_entries(path: str | Path) -> list[_RosterEntry]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        records = csv.reader(fh)
        header = next(records, None)
        if header is None or tuple(h.strip() for h in header) != ROSTER_HEADER:
            raise RosterError(f"unexpected header: expected {','.join(ROSTER_HEADER)}")
        entries = [_parse_entry(n, fields) for n, fields in enumerate(records, start=2) if fields]
    seen: set[str] = set()
    for entry in entries:
        if entry.recruiter.recruiter_id in seen:
            raise RosterError(f"duplicate recruiter_id '{entry.recruiter.recruiter_id}'")
        seen.add(entry.recruiter.recruiter_id)
    return entries


def load_roster(path: str | Path) -> list[Recruiter]:
    return [entry.recruiter for entry in _load_entries(path)]


def seed_recruiters(engine: Engine, path: str | Path) -> None:
    """Make the DB match the roster file, in one transaction: upsert its recruiters,
    replace their regions, and delete anyone no longer listed (D30), so a removed
    recruiter loses access on the next start."""
    entries = _load_entries(path)
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM recruiters WHERE recruiter_id <> ALL(:ids)"),
            {"ids": [e.recruiter.recruiter_id for e in entries]},
        )
        conn.execute(
            text(
                "INSERT INTO recruiters (recruiter_id, full_name, email, is_admin)"
                " VALUES (:recruiter_id, :full_name, :email, :is_admin)"
                " ON CONFLICT (recruiter_id) DO UPDATE SET full_name = EXCLUDED.full_name,"
                " email = EXCLUDED.email, is_admin = EXCLUDED.is_admin"
            ),
            [
                {
                    "recruiter_id": e.recruiter.recruiter_id,
                    "full_name": e.recruiter.full_name,
                    "email": e.email,
                    "is_admin": e.recruiter.is_admin,
                }
                for e in entries
            ],
        )
        conn.execute(
            text("DELETE FROM recruiter_regions WHERE recruiter_id = ANY(:ids)"),
            {"ids": [e.recruiter.recruiter_id for e in entries]},
        )
        regions = [
            {"recruiter_id": e.recruiter.recruiter_id, "region_code": region}
            for e in entries
            for region in e.recruiter.regions
        ]
        if regions:
            conn.execute(
                text(
                    "INSERT INTO recruiter_regions (recruiter_id, region_code)"
                    " VALUES (:recruiter_id, :region_code)"
                ),
                regions,
            )


_RECRUITERS_QUERY = (
    "SELECT r.recruiter_id, r.full_name, r.is_admin,"
    " coalesce(array_agg(rr.region_code ORDER BY rr.region_code)"
    " FILTER (WHERE rr.region_code IS NOT NULL), '{}') AS regions"
    " FROM recruiters r LEFT JOIN recruiter_regions rr USING (recruiter_id)"
)


def get_recruiter(conn: Connection, recruiter_id: str) -> Recruiter | None:
    row = conn.execute(
        text(_RECRUITERS_QUERY + " WHERE r.recruiter_id = :recruiter_id GROUP BY r.recruiter_id"),
        {"recruiter_id": recruiter_id},
    ).one_or_none()
    return None if row is None else Recruiter(row[0], row[1], row[2], tuple(row[3]))


def list_recruiters(conn: Connection) -> list[Recruiter]:
    rows = conn.execute(text(_RECRUITERS_QUERY + " GROUP BY r.recruiter_id ORDER BY r.recruiter_id"))
    return [Recruiter(r[0], r[1], r[2], tuple(r[3])) for r in rows]
