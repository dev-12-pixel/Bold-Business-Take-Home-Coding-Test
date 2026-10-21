# TechForce Take-Home Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the messy candidate CSV into Postgres through a FastAPI endpoint, serve it through a region-scoped read API enforced by Postgres RLS, show it in a React/TS table with a recruiter switcher, and prove it all with pytest.

**Architecture:** Pure-Python import pipeline (parse → Pydantic validate → dedup) with no DB access, followed by one batched upsert. Postgres owns authorization: the API connects as a non-superuser role, sets `app.recruiter_id` transaction-locally, and RLS policies on `candidates` decide visibility. React app talks to the API through the Vite dev proxy.

**Tech Stack:** Python 3.12 (in Docker, host is 3.15), FastAPI, Pydantic v2, email-validator, SQLAlchemy 2 Core + psycopg 3, Postgres 16, pytest; React 18 + Vite + TypeScript (Node 22 container).

**Spec:** `CLAUDE.md` (decisions D1–D27, audit table §3, expected report). Read it before any task.

## Global Constraints

- Every task appends one line to `CLAUDE.md` §6 Work log; any new decision gets a D-row in §2 before the code that uses it.
- Prefer rejecting with a reason over guessing. No fuzzy matching anywhere.
- SQL only via SQLAlchemy Core expressions or `text()` with bound parameters. No f-strings/`%`/`.format` into SQL. Ever.
- Writes batched: one multi-row statement per table per import; no per-row INSERT in a loop.
- Canonical regions: `US-MW, US-NE, US-SE, US-W, PH-MNL, CO-BOG`. Status enum: `active, screening, interviewing, withdrawn, on_hold`.
- Report row numbers: spreadsheet rows, header = 1 (D1).
- Images: `postgres:16-alpine`, `python:3.12-slim`, `node:22-alpine` (already pulled; if a pull fails, use `public.ecr.aws/docker/library/<name>` and retag).
- Backend tests run with: `docker compose run --rm api pytest -q` (exact command used everywhere below).
- Commits: small, one per task minimum, conventional messages, **no** Co-Authored-By/AI trailer (user instruction).

## Review Focus

1. Re-importing the same file → `imported 0, merged 43, rejected 10`; no duplicated rows (Task 5 test `test_reimport_is_idempotent`).
2. Search containing `%` or `_` is literal, not a wildcard (Task 6 `test_search_wildcards_are_literal`).
3. Pooled connection must not leak one recruiter's scope into the next request (Task 4 `test_scope_does_not_leak_across_transactions`, Task 6 `test_dana_then_caleb_same_client`).
4. Missing `X-Recruiter-Id` header → 403, not FastAPI's default 422 (Task 6 `test_missing_header_403`).
5. Upload that isn't UTF-8 or has the wrong header → 400 with a message, not a 500 (Task 5 `test_bad_file_400`).

---

### Task 0: Repo bootstrap + record new decisions

**Files:**
- Create: `.gitignore` (`.DS_Store`, `node_modules/`, `dist/`, `__pycache__/`, `.pytest_cache/`, `.venv/`, `*.pdf`)
- Modify: `CLAUDE.md` §2 (add D20–D27 below), §6

New decisions (all Claude's calls, add verbatim to §2):
- D20 Import auth: `POST /import` requires an admin `X-Recruiter-Id`; non-admin or unknown → 403.
- D21 Missing `X-Recruiter-Id` → 403 (same as unknown).
- D22 `GET /api/v1/candidates/{candidate_id}` out of scope → 404 (RLS makes it invisible; existence not leaked).
- D23 Report adds `merges: [{row, candidate_id, kept_row}]` — one entry per superseded record: `row`/`candidate_id` identify what was dropped, `kept_row` the file row that won. `row` is null when the dropped record was already in the DB (re-import).
- D24 Pagination: `page` ≥1 (default 1), `page_size` 1–100 (default 25); response `{items, total, page, page_size}`; order `applied_date DESC, candidate_id ASC`.
- D25 Search: case-insensitive substring over first_name, last_name, email, desired_role; `%`, `_`, `\` escaped; `status` must be in enum else 422.
- D26 The brief PDF is not committed (company document).
- D27 candidate_id claim: the first valid row to use an id owns it for the whole import; a later row with that id and a different email is rejected (D4), even if the owner itself is later superseded by email.

- [ ] Step 1: write `.gitignore`, add D20–D27, add work-log line.
- [ ] Step 2: commit `CLAUDE.md .gitignore candidates_import.csv recruiters.csv docs/` — `chore: scoping decisions, source data, implementation plan`.

---

### Task 1: Infrastructure skeleton

**Files:**
- Create: `docker-compose.yml`, `db/init/01-roles.sh`, `backend/Dockerfile`, `backend/requirements.txt`, `backend/app/__init__.py`, `backend/app/config.py`, `backend/app/main.py`, `backend/tests/test_health.py`, `backend/pytest.ini`

Compose services:
- `db`: postgres:16-alpine, `POSTGRES_USER=techforce_owner`, `POSTGRES_PASSWORD=owner_pw`, `POSTGRES_DB=techforce`, healthcheck `pg_isready`, mounts `./db/init:/docker-entrypoint-initdb.d:ro`.
- `api`: build `./backend`, depends on db healthy, mounts `./backend:/app` and `./candidates_import.csv`, `./recruiters.csv` into `/data/` read-only, port 8000, `uvicorn app.main:app --host 0.0.0.0 --reload`.
- `web` (added in Task 7).

`01-roles.sh` creates role `techforce_app LOGIN PASSWORD 'app_pw' NOSUPERUSER NOBYPASSRLS` and database `techforce_test` owned by `techforce_owner`.

`config.py` → `Settings` (pydantic-settings not needed; plain `os.environ`): `owner_url`, `app_url`, `recruiters_csv="/data/recruiters.csv"`; test DB chosen by env `TECHFORCE_DB` (default `techforce`, conftest sets `techforce_test`).

requirements: `fastapi uvicorn[standard] pydantic>=2.7 email-validator sqlalchemy>=2.0 psycopg[binary]>=3.1 python-multipart pytest httpx` (pinned exact versions at write time).

- [ ] Step 1: test `test_health`: `TestClient(create_app()).get("/healthz")` → 200 `{"status": "ok"}`.
- [ ] Step 2: run `docker compose run --rm api pytest -q` → FAIL (no app).
- [ ] Step 3: implement `create_app() -> FastAPI` in `app/main.py` with `/healthz`; module-level `app = create_app()`.
- [ ] Step 4: `docker compose up -d db && docker compose run --rm api pytest -q` → 1 passed; `docker compose exec db psql -U techforce_owner -c "\du"` shows `techforce_app` without Superuser/Bypass RLS.
- [ ] Step 5: work log + commit `chore: docker compose, api skeleton`.

---

### Task 2: Field normalizers (pure functions)

**Files:**
- Create: `backend/app/importer/__init__.py`, `backend/app/importer/normalize.py`
- Test: `backend/tests/test_normalize.py`

**Interfaces — Produces** (each raises `ValueError(message)` on invalid input; message text below is exact):
- `REGIONS: frozenset[str]`, `STATUSES: tuple[str, ...]` (order as in Global Constraints)
- `normalize_candidate_id(raw: str) -> str` — `"required"`, `"must match C-#### (got '{v}')"`
- `normalize_name(raw: str) -> str` — trim, NFC; `"required"`, `"contains characters other than letters, spaces, apostrophes, hyphens or periods"`. Allowed: `unicodedata.category(c)[0] in "LM"` or `c in " '’-."`.
- `normalize_email(raw: str) -> str` — trim, lowercase, then `email_validator.validate_email(v, check_deliverability=False)`; `"required"`, `"invalid address '{v}'"`.
- `normalize_region(raw: str) -> str` — trim+upper; exact match, else if no `-` match against codes with `-` removed; `"required"`, `"unknown region '{raw.strip()}'"`.
- `normalize_status(raw: str) -> str` — trim, lower, `re.sub(r"[\s-]+", "_")`; `"required"`, `"unknown status '{raw.strip()}'"`.
- `parse_date(raw: str) -> date` — formats in order `%Y-%m-%d`, `%m/%d/%Y`, `%d-%b-%Y` (strptime; `%b` is locale-C English, case-insensitive); `"required"`, `"not a valid date '{v}'"`.
- `parse_salary(raw: str) -> tuple[int | None, str | None]` — never raises; returns `(value, warning)`; regex `^\$?\d[\d,]*(\.\d+)?[kK]?$` after removing whitespace; `k` ×1000; non-whole result → null+warning; warning text `"salary '{raw}' is not numeric; stored as null"`.
- `clean_optional(raw: str) -> str | None` — trim; empty → None; no other change (notes keep `\n`).

- [ ] Step 1: parametrized tests using the audit's exact values:
  - email: `"  Alicia.Trent@Gmail.com "`→`"alicia.trent@gmail.com"`; `"marcus.reed[at]gmail.com"`, `"tina.holloway.gmail.com"`, `""` raise.
  - region: `"us-mw"`→`US-MW`, `" CO-BOG "`→`CO-BOG`, `"USW"`→`US-W`, `"phmnl"`→`PH-MNL`; `"ZZ-99"`, `""`, `"US_W"` raise.
  - status: `"ACTIVE"`→`active`, `"on hold"`→`on_hold`, `"On-Hold"`→`on_hold`; `"actve"`, `""` raise.
  - date: `"2026-05-14"`, `"06/30/2026"`→2026-06-30, `"14-May-2026"`→2026-05-14, `"14-MAY-2026"` ok; `"2026-02-30"`, `""`, `"30/06/2026"` raise.
  - salary: `"$95,000"`→95000, `"97,500"`→97500, `"85k"`→85000, `""`→(None, None), `"negotiable"`→(None, warning), `"-5"`→(None, warning).
  - name: `"Nguyễn"`, `"A."`, `"O'Connor"`, `"Castellanos-Ruiz"` ok; `"O'Connor'); DROP TABLE candidates;--"` raises; NFD `"Tomás"` input returns NFC.
  - candidate_id: `"C-1001"` ok; `"1001"`, `""` raise.
- [ ] Step 2: run → FAIL (module missing).
- [ ] Step 3: implement `normalize.py`.
- [ ] Step 4: run → all pass.
- [ ] Step 5: work log + commit `feat(import): field normalizers`.

---

### Task 3: Pydantic row model + pure import pipeline

**Files:**
- Create: `backend/app/importer/models.py`, `backend/app/importer/pipeline.py`
- Test: `backend/tests/test_pipeline.py`, fixture `backend/tests/conftest.py` (`raw_csv` fixture reads `/data/candidates_import.csv` as bytes)

**Interfaces:**
- Consumes: Task 2 functions.
- Produces:
  - `EXPECTED_HEADER: tuple[str, ...]` (the 12 columns in file order)
  - `class CandidateIn(BaseModel)`: fields `candidate_id, first_name, last_name, email, phone, region_code, desired_role, salary_expectation: int|None, applied_date: date, status, source, notes` — `field_validator(..., mode="before")` per field calling the normalizer. Salary warning is carried out-of-band (pipeline calls `parse_salary` itself and passes the int).
  - `class FileError(Exception)` — header mismatch / not UTF-8 / empty.
  - `@dataclass RawRow(row: int, values: dict[str, str])`
  - `parse_csv(data: bytes) -> list[RawRow]` — decode `utf-8-sig` (UnicodeDecodeError → `FileError("file is not valid UTF-8")`), `csv.reader(io.StringIO(text, newline=""))`, header must equal EXPECTED_HEADER after strip (`FileError("unexpected header: ...")`), row number = 1 + record index (header is row 1); wrong field count → kept as RawRow with `values=None` so validation rejects it with `"expected 12 fields, got N"`.
  - `@dataclass Rejection(row:int, candidate_id:str|None, reason:str)`, `ImportWarning(row, candidate_id, message)`, `Merge(row:int|None, candidate_id:str, kept_row:int)`
  - `@dataclass ImportPlan(survivors: list[tuple[int, CandidateIn]], rejected: list[Rejection], warnings: list[ImportWarning], merges: list[Merge])`
  - `build_plan(rows: list[RawRow]) -> ImportPlan`
- Reason format: every failing field as `"{field}: {message}"` joined by `"; "`, in column order. Strip Pydantic's `"Value error, "` prefix from `err["msg"]`.

Dedup algorithm in `build_plan` (D2/D3/D4/D27):
```
id_owner = {}            # candidate_id -> (row, email) first valid claimant
by_email = {}            # email -> (row, model) last wins
for row, model in valid rows in file order:
    owner = id_owner.get(model.candidate_id)
    if owner and owner.email != model.email:
        reject(row, f"candidate_id: {id} already used by row {owner.row} with a different email"); continue
    id_owner.setdefault(model.candidate_id, (row, model.email))
    if model.email in by_email: merges.append(Merge(prev_row, prev_id, kept_row=row))
    by_email[model.email] = (row, model)
survivors = sorted(by_email.values())   # by row
```
Warnings only for survivors (a superseded or rejected row's salary warning is dropped).

- [ ] Step 1: tests:
  - `test_full_file_plan(raw_csv)`: `len(survivors)==40`, `sorted(r.row for r in rejected)==[35,36,37,38,42,43,47,49,53,54]`, merges as `{(2,"C-1001",33),(5,"C-1004",32),(17,"C-1016",34)}`, `warnings==[]`.
  - `test_reasons(raw_csv)`: row 35 reason starts `"email: invalid address"`; row 37 `"email: required"`; row 38 starts `"last_name: contains characters"`; row 42 `"applied_date: not a valid date '2026-02-30'"`; row 43 `"applied_date: required"`; row 47 `"region_code: unknown region 'ZZ-99'"`; row 49 `"status: unknown status 'actve'"`; row 53 `"candidate_id: C-1010 already used by row 11 with a different email"`; row 54 `"region_code: required"`.
  - `test_survivor_values(raw_csv)`: survivor for `amara.diallo@gmail.com` is row 34 with `first_name "A."`, salary 110000, date 2026-06-20, candidate_id C-1032; row 33 survivor candidate_id C-1031; row 48 → status active, salary 85000; row 46 region US-W; row 50 status on_hold, salary None; row 52 notes contain `"\n"`; row 9 first_name `"Nguyễn"`.
  - `test_multiple_errors_all_reported`: synthetic row with bad email and bad region → reason contains both, email first.
  - `test_salary_warning_on_survivor`: synthetic valid row with salary `"negotiable"` → one warning, row imported with salary None.
  - `test_bad_header_raises` / `test_non_utf8_raises` (`b"\xff\xfe..."`) / `test_bom_ok`.
  - `test_wrong_field_count_rejected`.
- [ ] Step 2: run → FAIL.
- [ ] Step 3: implement `models.py`, `pipeline.py`.
- [ ] Step 4: run → pass.
- [ ] Step 5: work log + commit `feat(import): validation and dedup pipeline`.

---

### Task 4: Schema, RLS, recruiter seed, scoped sessions

**Files:**
- Create: `backend/app/schema.sql`, `backend/app/db.py`, `backend/app/recruiters.py`
- Modify: `backend/app/main.py` (lifespan: `migrate()` then `seed_recruiters()`), `backend/tests/conftest.py`
- Test: `backend/tests/test_rls.py`, `backend/tests/test_recruiters_seed.py`

schema.sql (idempotent, run by owner):
- `recruiters(recruiter_id text PK, full_name text NOT NULL, email text NOT NULL, is_admin bool NOT NULL)`
- `recruiter_regions(recruiter_id text REFERENCES recruiters ON DELETE CASCADE, region_code text CHECK (region_code IN (...6)), PRIMARY KEY (recruiter_id, region_code))`
- `candidates(id bigserial PK, candidate_id text UNIQUE NOT NULL, first_name, last_name, email text UNIQUE NOT NULL, phone, region_code text NOT NULL CHECK (IN 6), desired_role, salary_expectation integer CHECK (>=0), applied_date date NOT NULL, status text NOT NULL CHECK (IN 5), source, notes, created_at, updated_at timestamptz default now())`
- Index `candidates(region_code)`.
- `ALTER TABLE candidates ENABLE ROW LEVEL SECURITY; FORCE ROW LEVEL SECURITY;`
- Function `app_can_see(region text) RETURNS boolean STABLE` (SQL, `SECURITY INVOKER`): true iff a recruiter with `recruiter_id = current_setting('app.recruiter_id', true)` exists and (`is_admin` or has a `recruiter_regions` row for `region`). Unset/empty setting → false.
- Policies (drop-if-exists then create), `TO techforce_app`: `SELECT USING (app_can_see(region_code))`; `INSERT WITH CHECK (app_can_see(region_code))`; `UPDATE USING/WITH CHECK (app_can_see(region_code))`. No DELETE policy.
- Grants: `techforce_app` SELECT on recruiters, recruiter_regions; SELECT, INSERT, UPDATE on candidates; USAGE on the sequence.

**Interfaces — Produces:**
- `db.owner_engine() / db.app_engine() -> Engine` (cached per URL)
- `db.migrate(engine) -> None` — executes schema.sql
- `@contextmanager db.scoped(recruiter_id: str) -> Iterator[Connection]` — `app_engine().begin()`, then `SELECT set_config('app.recruiter_id', :rid, true)`; yields conn.
- `recruiters.RosterError(Exception)`; `recruiters.load_roster(path) -> list[Recruiter]` (D17 validation, uses `normalize_region` exact-only: roster regions must already be canonical); `recruiters.seed_recruiters(engine, path) -> None` (upsert recruiters, delete+insert regions, one transaction, batched)
- `recruiters.get_recruiter(conn, recruiter_id) -> Recruiter | None`; `Recruiter(recruiter_id, full_name, is_admin, regions: tuple[str,...])`
- conftest: session fixture sets `TECHFORCE_DB=techforce_test`, migrates, seeds; autouse fixture `TRUNCATE candidates RESTART IDENTITY` via owner; fixture `insert_candidates(rows)` via owner for read tests.

- [ ] Step 1: tests:
  - `test_app_role_without_setting_sees_nothing`: owner inserts one US-MW row; plain `app_engine().connect()` `SELECT count(*) FROM candidates` → 0.
  - `test_caleb_sees_only_his_regions`: owner inserts one row per region; `scoped("R-102")` → regions `{US-MW, US-NE}`.
  - `test_marisol` → `{PH-MNL, CO-BOG}`; `test_dana_sees_all` → 6; `test_unknown_id_sees_nothing` (`scoped("R-999")`) → 0.
  - `test_scope_does_not_leak_across_transactions`: engine with `pool_size=1`; `scoped("R-101")` then plain connect → 0 rows.
  - `test_app_role_cannot_insert_outside_scope`: `scoped("R-102")` insert PH-MNL row → raises `ProgrammingError`/`DBAPIError` (RLS violation).
  - `test_app_role_is_not_superuser`: `SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user` → `(False, False)`.
  - seed: real roster → 5 recruiters, R-101 admin with no region rows, R-102 regions `("US-MW","US-NE")`; tmp CSV with `*|US-MW` → RosterError; role `recruiter` with `*` → RosterError; region `ZZ-99` → RosterError.
- [ ] Step 2: run → FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: run → pass; full suite green.
- [ ] Step 5: work log + commit `feat(db): schema, RLS policies, recruiter seed`.

---

### Task 5: Import endpoint with batched upsert

**Files:**
- Create: `backend/app/importer/repository.py`, `backend/app/api/__init__.py`, `backend/app/api/deps.py`, `backend/app/api/imports.py`
- Modify: `backend/app/main.py` (include router)
- Test: `backend/tests/test_import_api.py`

**Interfaces:**
- Consumes: `parse_csv`, `build_plan`, `ImportPlan`, `scoped`, `get_recruiter`.
- Produces:
  - `deps.current_recruiter(x_recruiter_id: str | None = Header(None)) -> Recruiter` — None/unknown → `HTTPException(403, "unknown recruiter")`. Lookup via an app-role connection (recruiters table has no RLS).
  - `repository.apply_plan(conn, plan: ImportPlan) -> ImportReport`
  - `ImportReport` Pydantic: `imported:int, merged:int, rejected:list[{row,candidate_id,reason}], warnings:list[{row,candidate_id,message}], merges:list[{row,candidate_id,kept_row}]`
  - `POST /api/v1/candidates/import` multipart field `file`; admin only (D20) else 403; body > 5 MB → 413; `FileError` → 400 `{"detail": str(e)}`.

`apply_plan` (one transaction, inside `scoped(admin_id)`):
1. One `SELECT candidate_id, email FROM candidates WHERE candidate_id = ANY(:ids)`; survivors whose id belongs to a different existing email → rejected with `"candidate_id: {id} already used by an existing candidate with a different email"`.
2. One `insert(candidates).values([...]).on_conflict_do_update(index_elements=["email"], set_={all columns except id/created_at, updated_at=now()}).returning(candidates.c.email, text("(xmax = 0) AS inserted"))`.
3. `imported` = rows returned with `inserted=true`; `merged` = `len(plan.merges)` + rows returned with `inserted=false`. Each DB update appends `Merge(row=None, candidate_id=<existing record's candidate_id>, kept_row=<file row>)` (D23). The step-1 SELECT also returns existing ids by email for this purpose (`WHERE candidate_id = ANY(:ids) OR email = ANY(:emails)`).
4. Empty survivor list → skip insert.

- [ ] Step 1: tests (TestClient, header `X-Recruiter-Id: R-101`):
  - `test_full_import_report`: response 200, `imported==40, merged==3`, rejected rows `[35,36,37,38,42,43,47,49,53,54]`, `warnings==[]`; owner `count(*)==40`.
  - `test_reimport_is_idempotent`: import twice → second `imported==0, merged==40, len(rejected)==10`; count still 40.
  - `test_dedup_last_wins_in_db`: row for `amara.diallo@gmail.com` has candidate_id C-1032, first_name "A."; no row with C-1001 or C-1016.
  - `test_invalid_email_rejected`: rows 35/36/37 in rejected with email reasons; `marcus.reed[at]gmail.com` not in DB.
  - `test_injection_rows`: row 38 rejected; owner `SELECT to_regclass('candidates')` not null and count 40; C-1037 notes == `"' OR '1'='1"` byte-exact.
  - `test_injection_in_every_field`: synthetic CSV where notes/role/source = `"x'); DROP TABLE candidates;--"` → imported, stored literally, table intact.
  - `test_import_requires_admin`: R-102 → 403; no header → 403; R-999 → 403.
  - `test_bad_file_400`: wrong header → 400; `b"\xff\xfe\x00"` → 400.
  - `test_writes_are_batched`: SQLAlchemy `before_cursor_execute` listener on app engine counts statements starting with `INSERT INTO candidates` during a full import → exactly 1.
  - `test_db_collision_rejected`: owner pre-inserts `C-2000 / a@x.com`; import CSV with `C-2000 / b@x.com` → rejected with existing-collision reason.
- [ ] Step 2: run → FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: run → pass.
- [ ] Step 5: manual: `docker compose up -d && curl -s -H 'X-Recruiter-Id: R-101' -F file=@candidates_import.csv localhost:8000/api/v1/candidates/import | python3 -m json.tool` → counts 40/3/10.
- [ ] Step 6: work log + commit `feat(api): candidate import endpoint`.

---

### Task 6: Scoped read API

**Files:**
- Create: `backend/app/api/candidates.py`, `backend/app/api/recruiters.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_read_api.py`

**Interfaces — Produces (consumed by Task 7):**
- `GET /api/v1/recruiters` (no header) → `[{recruiter_id, full_name, is_admin, regions: string[]}]` ordered by recruiter_id.
- `GET /api/v1/candidates?search=&status=&page=&page_size=` (D21, D24, D25) → `{items: CandidateOut[], total, page, page_size}`; `CandidateOut = {candidate_id, first_name, last_name, email, region_code, desired_role, status, applied_date}` (ISO date string).
- `GET /api/v1/candidates/{candidate_id}` → `CandidateOut` or 404 (D22).
- All queries run inside `scoped(recruiter.recruiter_id)` with **no** region predicate in Python — RLS is the only scoping. Total via `count(*) over ()` or a second count in the same transaction.
- Search escaping: `escape = "\\"`; replace `\`→`\\`, `%`→`\%`, `_`→`\_`; `ilike(f"%{term}%", escape="\\")` with the term as a bound parameter.

- [ ] Step 1: tests (fixture imports the real CSV once per test via the endpoint):
  - `test_caleb_cannot_fetch_outside_regions`: R-102 GET `/candidates/C-1007` (Grace Lim, PH-MNL) → 404.
  - `test_admin_can_fetch`: R-101 same → 200, `first_name=="Grace"`.
  - `test_marisol_can_fetch_own`: R-103 → 200.
  - `test_list_scoped`: R-102 list page_size=100 → every `region_code in {"US-MW","US-NE"}`, total == count of survivors in those regions (computed from `build_plan` in the test, not hard-coded); R-103 → only PH-MNL/CO-BOG; R-101 total 40.
  - `test_unknown_recruiter_403` (`R-999`), `test_missing_header_403`.
  - `test_search_unicode`: R-103 `search=nguy` → contains C-1008 with `first_name=="Nguyễn"`; `search=cárdenas` → C-1010.
  - `test_status_filter`: R-101 `status=on_hold` → only C-1048; `status=bogus` → 422.
  - `test_search_wildcards_are_literal`: `search=%` → total 0; `search=_` → total 0.
  - `test_pagination`: R-101 page_size=15 → page 1 has 15, page 3 has 10, page 4 empty with total 40; page_size=101 → 422; page=0 → 422.
  - `test_dana_then_caleb_same_client`: R-101 list then R-102 list on same TestClient → Caleb totals stay scoped.
  - `test_recruiters_list`: 5 entries, R-101 `is_admin` true.
- [ ] Step 2: run → FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: run → pass.
- [ ] Step 5: work log + commit `feat(api): RLS-scoped candidate read API`.

---

### Task 7: React recruiter view

**Files:**
- Create: `frontend/` via `npm create vite@latest frontend -- --template react-ts` (run in node:22-alpine container if host Node 26 misbehaves), then `frontend/src/api.ts`, `frontend/src/App.tsx`; trim template CSS.
- Modify: `frontend/vite.config.ts` (proxy `/api` → `process.env.API_URL ?? "http://localhost:8000"`, `server.host: true`), `docker-compose.yml` (`web`: node:22-alpine, `working_dir /app`, mounts `./frontend`, `npm install && npm run dev`, port 5173, `API_URL=http://api:8000`).

**Interfaces:**
- Consumes: Task 6 endpoints.
- `api.ts`: types `Recruiter`, `Candidate`, `Page<T>`; `STATUSES` (same 5 values); `fetchRecruiters(): Promise<Recruiter[]>`; `fetchCandidates(recruiterId: string, q: {search: string; status: string; page: number}): Promise<Page<Candidate>>` (sets `X-Recruiter-Id`; non-2xx → throws `Error` with status + detail).
- `App.tsx`: recruiter `<select>` (default R-102 Caleb), search `<input>` debounced 300 ms, status `<select>` ("All" + enum), table columns Name (`first last`), Email, Region, Role, Status, Applied; Prev/Next + "page X of Y (N total)"; error line; switching recruiter or filters resets page to 1; stale responses ignored (AbortController).
- Unicode: `index.html` has `<meta charset="UTF-8">`; render strings as text nodes (no `dangerouslySetInnerHTML`).

- [ ] Step 1: implement.
- [ ] Step 2: `docker compose run --rm web sh -c "npm install && npx tsc -b && npm run build"` → exit 0.
- [ ] Step 3: `docker compose up -d`, open http://localhost:5173: Caleb shows only US-MW/US-NE; switch to Marisol → PH-MNL/CO-BOG incl. "Nguyễn Thị Hoa", "Sofía Cárdenas", "Tomás Herrera"; Dana → 40 total; search "müller" finds Jürgen; status filter on_hold → Victor Hale.
- [ ] Step 4: work log + commit `feat(web): recruiter view`.

---

### Task 8: README, NOTES.md, final verification

**Files:**
- Create: `README.md` (prereqs: Docker; `docker compose up -d`; import curl; open UI; run tests command; reset: `docker compose down -v`), `NOTES.md` (≤1 page: dedup/normalization rules summarized from CLAUDE.md §2 with row evidence; AI usage log — leave the "what I delegated / caught and corrected" bullets as clearly marked placeholders **for the user to fill in personally**, since it must reflect their own experience; next steps: accent-insensitive search via `unaccent`, real auth, import audit table, async job for large files).
- Modify: `CLAUDE.md` §6.

- [ ] Step 1: write README, NOTES.
- [ ] Step 2: clean-machine check: `docker compose down -v && docker compose up -d --build` then follow README verbatim; import returns 40/3/10.
- [ ] Step 3: `docker compose run --rm api pytest -q` → all pass, 0 failures; paste the summary line into the work log.
- [ ] Step 4: commit `docs: README and NOTES`.
