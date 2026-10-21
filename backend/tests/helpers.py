from sqlalchemy import text


def insert_candidates(engine, *rows: dict) -> None:
    """Insert rows as the owner (bypasses RLS). Each dict overrides the defaults."""
    defaults = {
        "first_name": "Test",
        "last_name": "Person",
        "phone": None,
        "desired_role": "QA Engineer",
        "salary_expectation": None,
        "applied_date": "2026-07-01",
        "status": "active",
        "source": None,
        "notes": None,
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO candidates (candidate_id, first_name, last_name, email, phone,"
                " region_code, desired_role, salary_expectation, applied_date, status, source,"
                " notes) VALUES (:candidate_id, :first_name, :last_name, :email, :phone,"
                " :region_code, :desired_role, :salary_expectation, :applied_date, :status,"
                " :source, :notes)"
            ),
            [{**defaults, **row} for row in rows],
        )
