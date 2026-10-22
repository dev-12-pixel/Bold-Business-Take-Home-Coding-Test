# TechForce — candidate import & scoped recruiter view

FastAPI + PostgreSQL 16 + React/TypeScript. The app imports a messy candidate CSV, then serves
it through an API where each recruiter sees only candidates in their assigned regions. That
scoping is enforced by **PostgreSQL Row-Level Security**, not by application code.

## Clean setup

**Prerequisites:** Docker with Compose v2, and nothing else. Python 3.12, Node 22 and
Postgres 16 all run in containers.

1. Clone the repo.
2. Put the two source files from the brief at the repo root. They are git-ignored on purpose
   because they are client data:
   ```
   ./candidates_import.csv
   ./recruiters.csv
   ```
3. Start everything:
   ```bash
   docker compose up -d --build     # db :5432, api :8000, web :5173
   ```
   On startup the API applies `backend/app/schema.sql` and syncs the recruiter table with
   `recruiters.csv`. The first `web` start runs `npm install`, which takes about a minute.
4. Import the sample file. Only an admin may import:
   ```bash
   curl -s -H 'X-Recruiter-Id: R-101' -F file=@candidates_import.csv \
     http://localhost:8000/api/v1/candidates/import | python3 -m json.tool
   ```
   Expected result: `imported 40, merged 3`, and 10 rejected rows (35, 36, 37, 38, 42, 43,
   47, 49, 53, 54), each with a reason.
5. Open **http://localhost:5173** and use the recruiter dropdown. Caleb (US-MW, US-NE) sees
   19 candidates, Marisol (PH-MNL, CO-BOG) sees 9, and Dana (admin) sees all 40.

## Commands

| What | Command |
|---|---|
| Backend tests (real Postgres, separate `techforce_test` DB) | `docker compose run --rm api pytest -q` |
| Backend lint | `docker compose run --rm api ruff check .` |
| Backend format check | `docker compose run --rm api ruff format --check .` |
| Frontend tests (vitest) | `docker compose run --rm web npm test` |
| Frontend lint (ESLint + `tsc -b`) | `docker compose run --rm web npm run lint` |
| Frontend format check (Prettier) | `docker compose run --rm web npm run format:check` |
| Apply formatting | `docker compose run --rm api ruff format .` · `docker compose run --rm web npm run format` |
| API logs | `docker compose logs -f api` |
| psql (owner) | `docker compose exec db psql -U techforce_owner -d techforce` |
| Wipe all data and start over | `docker compose down -v && docker compose up -d --build` |

## API

Every candidate endpoint needs `X-Recruiter-Id` (R-101…R-105). If it is missing or unknown,
the response is **403**.

| Method | Path | Who | Returns |
|---|---|---|---|
| POST | `/api/v1/candidates/import` | admin only (R-101) | `{imported, merged, rejected[{row, candidate_id, reason}], warnings[{row, candidate_id, message}], merges[{row, candidate_id, kept_row}]}` |
| GET | `/api/v1/candidates?search=&status=&page=&page_size=` | any recruiter | `{items, total, page, page_size}` with only rows in the caller's regions |
| GET | `/api/v1/candidates/{candidate_id}` | any recruiter | the candidate, or 404 if it is outside the caller's regions |
| GET | `/api/v1/recruiters` | no header needed | roster for the UI switcher |
| GET | `/healthz` | — | `{"status": "ok"}` |

| Parameter / case | Rule |
|---|---|
| `search` | case-insensitive substring of first name, last name, full name, email or role; `%` `_` `\` are literal; at most 200 chars |
| `status` | `active`, `screening`, `interviewing`, `withdrawn` or `on_hold`; anything else → 422 |
| `page` / `page_size` | 1–100000 / 1–100 (default 1 / 25); order is newest `applied_date` first |
| import `row` | spreadsheet row number: the header is row 1 |
| import errors | non-admin → 403 (upload never read); over 5 MB → 413; not UTF-8, wrong header, NUL bytes, malformed quoting or empty file → 400; no `file` field → 422 |

## How the scoping works

- The API connects as `techforce_app`, a role with `NOSUPERUSER NOBYPASSRLS` and no DELETE
  or TEMP privilege.
- Each request runs in one transaction that sets `app.recruiter_id` with
  `set_config(…, true)`. The setting is transaction-local, so a pooled connection can't leak
  it to the next request.
- RLS on `candidates` is enabled and forced. The SELECT, INSERT and UPDATE policies call
  `app_can_see(region_code)`, which is true only for an admin or an assigned region. Its
  `search_path` is pinned, so a temp table can't impersonate `recruiters`.
- No Python code filters by region. A new endpoint that queries `candidates` is scoped
  automatically, and a connection with no recruiter set sees zero rows.

## Project layout

```
backend/
  app/
    main.py              app factory; startup = migrate + roster sync
    config.py, db.py     settings, engines, scoped() transaction helper
    schema.sql           tables, CHECK constraints, RLS policies, app_can_see()
    tables.py            SQLAlchemy Core table definition
    recruiters.py        strict roster load + seed
    api/                 routers: imports.py, candidates.py, recruiters.py; deps.py (X-Recruiter-Id)
    importer/
      normalize.py       field rules (email, region, status, date, salary, names)
      models.py          Pydantic v2 CandidateIn
      pipeline.py        parse_csv → build_plan (validate, id claims, dedup)
      repository.py      import_rows: advisory lock + batched upsert
      schemas.py         ImportReport
  tests/                 pytest: normalizers, pipeline, RLS, seed, import API, read API
  ruff.toml, pytest.ini, requirements.txt, Dockerfile
frontend/
  src/App.tsx, api.ts    table, recruiter switcher, search, status filter, pager
  src/App.test.tsx       vitest
  eslint.config.js, .prettierrc.json, vite.config.ts (proxies /api → api:8000)
db/init/01-roles.sh      creates techforce_app and techforce_test (first start only)
docker-compose.yml
CLAUDE.md                every decision (D1–D35) and a work log
NOTES.md                 rules summary, AI usage log, next steps
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `api` keeps restarting, or a log mentions `/data/recruiters.csv` | The CSVs aren't at the repo root. Docker then mounts an empty directory in their place. Add the files, then run `docker compose down && docker compose up -d`. |
| `role "techforce_app" does not exist`, or the test DB is missing | `db/init` runs only on an empty volume. Run `docker compose down -v` and bring it up again. |
| `port is already allocated` (5432, 8000 or 5173) | Stop whatever is using the port, or change the left-hand side of `ports:` in `docker-compose.yml`. |
| Image pull fails or times out (Docker Hub over IPv6) | Run `docker pull public.ecr.aws/docker/library/postgres:16-alpine`, then `docker tag public.ecr.aws/docker/library/postgres:16-alpine postgres:16-alpine`. Do the same for `python:3.12-slim` and `node:22-alpine`. |
| UI shows `403: unknown recruiter` | The recruiter isn't in `recruiters.csv`. The roster is re-synced on every API start. |
| UI table is empty for everyone | Nothing has been imported yet. Run step 4. |
| Import returns 403 | Only an admin (`R-101`) may import. |
| Schema change not applied | Restart the API (`docker compose restart api`). The migration is idempotent and runs on startup. |
| Tests can't connect | The `db` service must be healthy: `docker compose up -d db`. |
| Frontend changes not picked up | `web` runs the Vite dev server with hot reload. If it's stuck: `docker compose restart web`. |
