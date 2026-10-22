"""Writes an import to Postgres in one transaction with batched statements."""

from dataclasses import asdict

from sqlalchemy import Connection, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert

from app.importer.pipeline import Merge, RawRow, build_plan
from app.importer.schemas import ImportReport
from app.tables import candidates

# Postgres caps a statement at 65535 bind parameters; 1000 rows x 12 columns stays well under.
BATCH_SIZE = 1000

# Imports take this transaction-level advisory lock, so they run one at a time:
# each sees the previous one's committed rows and its id/email snapshot stays true.
IMPORT_LOCK_KEY = 0x7EC4F0

_UPDATABLE = [
    c.name for c in candidates.columns if c.name not in ("id", "email", "created_at", "updated_at")
]


def import_rows(conn: Connection, rows: list[RawRow]) -> ImportReport:
    """`conn` must be scoped to an admin (RLS checks every row written)."""
    conn.execute(select(func.pg_advisory_xact_lock(IMPORT_LOCK_KEY)))
    file_ids = {raw.fields[0].strip() for raw in rows if raw.fields}
    db_claims = dict(
        conn.execute(
            select(candidates.c.candidate_id, candidates.c.email).where(
                candidates.c.candidate_id.in_(file_ids)
            )
        ).all()
    )
    plan = build_plan(rows, db_claims)
    merges = list(plan.merges)

    emails = [model.email for _, model in plan.survivors]
    id_by_email = dict(
        conn.execute(
            select(candidates.c.email, candidates.c.candidate_id).where(
                candidates.c.email.in_(emails)
            )
        ).all()
    )
    rows_by_email = {model.email: row for row, model in plan.survivors}
    values = [model.model_dump() for _, model in plan.survivors]

    imported = 0
    for start in range(0, len(values), BATCH_SIZE):
        stmt = insert(candidates).values(values[start : start + BATCH_SIZE])
        stmt = stmt.on_conflict_do_update(
            index_elements=[candidates.c.email],
            set_={**{name: stmt.excluded[name] for name in _UPDATABLE}, "updated_at": func.now()},
        ).returning(candidates.c.email, literal_column("(xmax = 0)").label("inserted"))
        for email, inserted in conn.execute(stmt):
            if inserted:
                imported += 1
            else:
                merges.append(Merge(None, id_by_email[email], rows_by_email[email]))

    return ImportReport(
        imported=imported,
        merged=len(merges),
        rejected=[asdict(r) for r in sorted(plan.rejected, key=lambda r: r.row)],
        warnings=[asdict(w) for w in plan.warnings],
        merges=[asdict(m) for m in merges],
    )
