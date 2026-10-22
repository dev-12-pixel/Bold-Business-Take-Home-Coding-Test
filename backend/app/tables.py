"""SQLAlchemy Core view of the tables in schema.sql (which is the source of truth)."""

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Table,
    Text,
)

metadata = MetaData()

candidates = Table(
    "candidates",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("candidate_id", Text, nullable=False, unique=True),
    Column("first_name", Text, nullable=False),
    Column("last_name", Text, nullable=False),
    Column("email", Text, nullable=False, unique=True),
    Column("phone", Text),
    Column("region_code", Text, nullable=False),
    Column("desired_role", Text),
    Column("salary_expectation", Integer),
    Column("applied_date", Date, nullable=False),
    Column("status", Text, nullable=False),
    Column("source", Text),
    Column("notes", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
