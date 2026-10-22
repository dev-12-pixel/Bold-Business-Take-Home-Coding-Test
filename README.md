# TechForce — candidate import & scoped recruiter view

FastAPI + PostgreSQL + React/TypeScript. Imports a messy candidate CSV, then serves it
through an API where each recruiter sees only candidates in their assigned regions —
enforced by **PostgreSQL Row-Level Security**, not application code.

## Prerequisites

- Docker with Compose v2. Nothing else (Python, Node and Postgres all run in containers).
- The two source files from the brief placed at the repo root. They are git-ignored on
  purpose, since they're client data:
  ```
  ./candidates_import.csv
  ./recruiters.csv
  ```

## Run it

```bash
docker compose up -d --build        # db :5432, api :8000, web :5173
```

On startup the API applies `backend/app/schema.sql` and syncs recruiters from `recruiters.csv`
(anyone removed from the file loses access on the next start).
Candidates are loaded through the import endpoint (admin only):

```bash
curl -s -H 'X-Recruiter-Id: R-101' -F file=@candidates_import.csv \
  http://localhost:8000/api/v1/candidates/import | python3 -m json.tool
# → imported 40, merged 3, rejected 10 (rows 35,36,37,38,42,43,47,49,53,54)
```

Open **http://localhost:5173** and use the recruiter dropdown: Caleb (US-MW, US-NE) sees 19,
Marisol (PH-MNL, CO-BOG) 9, Dana (admin) all 40.

## Tests

```bash
docker compose run --rm api pytest -q    # backend: 173 tests against real Postgres
docker compose run --rm web npm test     # frontend: 4 vitest tests
```

Backend tests use a separate `techforce_test` database and never touch dev data.

## API

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/candidates/import` | multipart `file`; admin `X-Recruiter-Id` only. Returns `{imported, merged, rejected[{row, candidate_id, reason}], warnings[], merges[]}` |
| GET | `/api/v1/candidates?search=&status=&page=&page_size=` | scoped by RLS; `{items, total, page, page_size}` |
| GET | `/api/v1/candidates/{candidate_id}` | 404 if outside the caller's regions |
| GET | `/api/v1/recruiters` | roster for the switcher |

Missing or unknown `X-Recruiter-Id` → **403**. `row` in the import report is the spreadsheet
row (header = row 1).

## How the scoping works

- The API connects as `techforce_app`: `NOSUPERUSER NOBYPASSRLS`, with no DELETE grant.
- Each request runs in a transaction that sets `app.recruiter_id` with
  `set_config(..., true)` (transaction-local, so a pooled connection can't leak scope).
- `candidates` has RLS **enabled and forced**. The policies call `app_can_see(region_code)`,
  which is true only if that recruiter is an admin or is assigned the region.
- Python has no region filter anywhere. Any new endpoint that queries `candidates` is scoped
  automatically, and a query with no recruiter set returns zero rows.

## Layout

```
backend/app/importer/   normalize.py (field rules) → pipeline.py (parse/validate/dedup) → repository.py (batched upsert)
backend/app/schema.sql  tables, CHECK constraints, RLS policies
backend/app/api/        FastAPI routers + X-Recruiter-Id dependency
backend/tests/          pytest suite
frontend/src/           App.tsx, api.ts
CLAUDE.md               every decision (D1–D29) + work log
NOTES.md                rules summary, AI usage log, next steps
```

## Reset

```bash
docker compose down -v   # drops the database volume; next `up` starts clean
```
