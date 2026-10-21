"""Writes an ImportPlan to Postgres in one transaction with batched statements."""
from dataclasses import asdict

from sqlalchemy import Connection, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.importer.pipeline import ImportPlan, Merge, Rejection
from app.importer.schemas import ImportReport
from app.tables import candidates

# Postgres caps a statement at 65535 bind parameters; 1000 rows x 12 columns stays well under.
BATCH_SIZE = 1000

_UPDATABLE = [
    c.name for c in candidates.columns if c.name not in ("id", "email", "created_at", "updated_at")
]


def apply_plan(conn: Connection, plan: ImportPlan) -> ImportReport:
    """`conn` must be scoped to an admin (RLS checks every row written)."""
    rejected = list(plan.rejected)
    merges = list(plan.merges)
    survivors = plan.survivors

    ids = [model.candidate_id for _, model in survivors]
    emails = [model.email for _, model in survivors]
    existing = conn.execute(
        select(candidates.c.candidate_id, candidates.c.email).where(
            or_(candidates.c.candidate_id.in_(ids), candidates.c.email.in_(emails))
        )
    ).all()
    email_by_id = {cid: email for cid, email in existing}
    id_by_email = {email: cid for cid, email in existing}

    rows_by_email: dict[str, int] = {}
    values = []
    for row, model in survivors:
        owner_email = email_by_id.get(model.candidate_id)
        if owner_email is not None and owner_email != model.email:
            rejected.append(
                Rejection(
                    row,
                    model.candidate_id,
                    f"candidate_id: {model.candidate_id} already used by an existing "
                    "candidate with a different email",
                )
            )
            continue
        rows_by_email[model.email] = row
        values.append(model.model_dump())

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

    kept = set(rows_by_email.values())
    return ImportReport(
        imported=imported,
        merged=len(merges),
        rejected=[asdict(r) for r in sorted(rejected, key=lambda r: r.row)],
        warnings=[asdict(w) for w in plan.warnings if w.row in kept],
        merges=[asdict(m) for m in merges],
    )
