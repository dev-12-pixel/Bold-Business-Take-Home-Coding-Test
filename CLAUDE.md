# CLAUDE.md — TechForce take-home

Bold Business take-home: import `candidates_import.csv` into PostgreSQL (FastAPI), expose a
region-scoped read API, React/TS recruiter view, pytest suite, NOTES.md. Brief: 
`Full-Stack Engineer — Coding Test.pdf`.

**Working rule:** every decision and every change made in this repo is recorded in this file
(Decisions + Work log). If code and this file disagree, this file is wrong until updated.
Prefer rejecting with a reason over guessing. No fuzzy matching anywhere.

## 1. Source file facts (verified with Python `csv`, not line counts)
| | candidates_import.csv | recruiters.csv |
|---|---|---|
| Size | 7,125 bytes | 403 bytes |
| Encoding | UTF-8, no BOM, no NUL, no tabs; non-ASCII already NFC | UTF-8, no BOM |
| Line endings | CRLF ×54 + 2 bare LF inside quoted notes (row 52) → 56 physical lines | CRLF ×6 |
| Records | 53 + header | 5 + header |
| Fields | 12 on every record | 5 on every record |

## 2. Decisions
| # | Topic | Decision | Owner |
|---|---|---|---|
| D1 | Row numbering in report | Spreadsheet row: header = row 1, first candidate = row 2. Report also carries `candidate_id`. | Claude's call |
| D2 | Same-email duplicates | Dedup key = normalized email. **Last occurrence in file wins**; earlier rows with that email are dropped (whole record replaced, incl. candidate_id). Each dropped row counts as `merged`. | User |
| D3 | Exact duplicates | Same rule as D2 (identical, so no visible change); counts as `merged`. | User (via D2) |
| D4 | candidate_id collision, different email | Different person, so not a merge. First holder keeps the id; later row rejected: "candidate_id C-xxxx already used by row N with a different email". | Claude's call — flagged for user |
| D5 | Re-import / existing DB rows | DB rows are "earlier" than the file → file row overwrites by email (upsert). Invariant: imported + merged + rejected = data rows in the file. Re-importing the same file: imported 0, merged 43 (3 in-file + 40 updates), rejected 10. | Claude's call |
| D6 | Names | Required, trimmed, NFC. Allowlist: Unicode letters, combining marks, space, `'`, `’`, `-`, `.`. Anything else → reject. Row 38 (`O'Connor'); DROP TABLE…`) rejected by this rule. | User |
| D7 | Email | Required. Trim + lowercase whole address; syntax check with email-validator (no DNS). No de-obfuscation of `[at]`. | Claude (brief) |
| D8 | Region | Required. Trim; must be ASCII (else reject — `uſ-mw` would upper-case to US-MW); uppercase; exact match to US-MW, US-NE, US-SE, US-W, PH-MNL, CO-BOG; or, if no hyphen, exact match against codes with hyphen removed (USW→US-W). Anything else → reject. | User (USW; ASCII 2026-10-21) |
| D9 | Status enum | `active, screening, interviewing, withdrawn, on_hold`. Input trimmed, lowercased, spaces/hyphens → `_`, then exact match. `actve` → reject. | User |
| D10 | applied_date | Required, ASCII digits only, exact shapes: `YYYY-MM-DD` (zero-padded), `M/D/YYYY` or `MM/DD/YYYY`, `D-Mon-YYYY` (English month abbrev, case-insensitive). **Slash dates are accepted only when unambiguous** — if both parts ≤ 12 and differ (`05/06/2026`) → reject "ambiguous date … use YYYY-MM-DD" (Bogotá/Manila sources write DD/MM); otherwise read as US MM/DD (`06/30/2026`), so `30/06/2026` stays rejected. Must be a real calendar date between 2000-01-01 and 31 Dec of next year. Stored as DATE. No outcome in candidates_import.csv changes. | User (revised 2026-10-21) |
| D11 | Salary | Optional. ASCII digits only (else null + warning). Strip `$`, `,`, whitespace; optional trailing `k`/`K` ×1000; must yield a non-negative whole number ≤ 2,147,483,647 (Postgres integer). Empty → null. Unparseable (`negotiable`) → null + warning (never rejects the row alone). No currency stored. | User (85k) |
| D12 | candidate_id | Required, trimmed, must match `C-[0-9]{4}` (ASCII digits; `C-١٢٣٤` rejected). | Claude's call (ASCII: User 2026-10-21) |
| D13 | Phone, source, notes | Optional, trimmed, stored verbatim (notes keep newlines). Hostile text (row 39 `' OR '1'='1`) stored literally. | Claude's call |
| D14 | Pipeline order | `parse_csv` (file checks, D15) → in one transaction as the admin: advisory lock (D32) → SELECT DB claims for the file's candidate_ids → `build_plan`: validate each row (collect **all** field errors into the reason), reject DB/in-file id clashes (D31, D27), dedup by email → SELECT existing ids by email → one `INSERT … ON CONFLICT (email) DO UPDATE` per 1000 rows (`repository.import_rows`). | Claude's call |
| D15 | File-level checks | Must be UTF-8 (BOM stripped); header must equal the 12 expected columns; no NUL bytes; strict CSV quoting (an unbalanced quote or a cell over csv's 128 KB limit is an error, never silently merged rows) — any of these → HTTP 400. Rows with wrong field count → rejected. | Claude's call |
| D16 | Report shape | `{imported, merged, rejected:[{row, candidate_id, reason}], warnings:[{row, candidate_id, message}], merges:[…]}` (merges per D23); rejected sorted by row. | Claude's call |
| D17 | Recruiters | Seeded from recruiters.csv. `*` must be the sole token and iff role=admin; unknown region fails the seed. | Claude's call |
| D18 | Authorization | Postgres Row-Level Security with a non-superuser app role; per-request `SELECT set_config('app.recruiter_id', :id, true)` (transaction-local, `db.scoped()`); SELECT/INSERT/UPDATE policies call `app_can_see(region_code)` (admin or assigned region; hardened per D34); no DELETE grant. Unknown X-Recruiter-Id → 403 before querying. | Claude's call |
| D19 | Stack | FastAPI, Pydantic v2, SQLAlchemy 2 + psycopg, Postgres 16 in docker-compose; React + Vite + TS; pytest against real Postgres; vitest + testing-library for the UI. Lint/format per D35. | Claude's call |
| D20 | Import auth | `POST /import` requires an admin `X-Recruiter-Id`; non-admin or unknown → 403. | Claude's call |
| D21 | Missing header | Missing `X-Recruiter-Id` → 403 (same as unknown), not FastAPI's 422. | Claude's call |
| D22 | Single fetch | `GET /api/v1/candidates/{candidate_id}` out of scope → 404 (RLS makes it invisible; existence not leaked). | Claude's call |
| D23 | Merge detail | Report adds `merges: [{row, candidate_id, kept_row}]` — one entry per superseded record: `row`/`candidate_id` = what was dropped, `kept_row` = file row that won; `row` null when the dropped record was already in the DB. | Claude's call |
| D24 | Pagination | `page` ≥1 (default 1), `page_size` 1–100 (default 25); response `{items, total, page, page_size}`; order `applied_date DESC, candidate_id ASC`. | Claude's call |
| D25 | Search | Case-insensitive substring (ILIKE, term NFC-normalized) over first_name, last_name, `first_name || ' ' || last_name`, email, desired_role; `%`, `_`, `\` escaped (literal); `status` must be in enum else 422. `search` ≤ 200 chars and no NUL, `page` ≤ 100000, path id no NUL → otherwise 422 (hostile input never 500s). | Claude's call |
| D26 | Brief PDF | Not committed (company document); `.gitignore` excludes `*.pdf`. | Claude's call |
| D27 | ID claim | The first valid row to use a candidate_id owns it for the whole import; a later row with that id and a different email is rejected (D4), even if the owner is later superseded by email. | Claude's call |
| D28 | Source files in git | `candidates_import.csv`, `recruiters.csv` and the brief PDF are git-ignored and untracked; they stay on disk at the repo root and are mounted into the API container at `/data/`. README must tell a reader to place them there. | User |
| D29 | UI style | "Midnight Minimalist": dark theme — near-black navy background, muted slate text, hairline borders, a single soft-indigo accent, uppercase micro-labels, status pills, monospace region codes. Plain CSS, no UI library. | User |
| D30 | Roster sync | Startup seed makes the DB equal recruiters.csv: recruiters not in the file are deleted (regions cascade), so a removed recruiter/admin loses access. | Claude's call (review fix) |
| D31 | DB id claims before dedup | candidate_ids already in the DB are passed into `build_plan` as the earliest claims; a row clashing with one is rejected *before* dedup, so it never supersedes an earlier valid row with its email (was: winner rejected after dedup → earlier row lost, report claimed a merge). | Claude's call (review fix; applies existing D4/D27 rule consistently) |
| D32 | Concurrent imports | `pg_advisory_xact_lock` at the start of each import transaction serializes imports; DB work runs in the threadpool so an import doesn't block the event loop. | Claude's call (review fix) |
| D33 | Upload handling | Import endpoint reads the multipart body from `Request` only **after** the admin check; declared Content-Length > cap → 413 unread; streamed body counted and cut off at cap + 64 KB envelope → 413. | Claude's call (review fix) |
| D34 | RLS function hardening | `app_can_see` reads `public.recruiters`/`public.recruiter_regions` with `SET search_path = pg_catalog, public, pg_temp`; `REVOKE TEMPORARY ON DATABASE … FROM PUBLIC` in the migration. A temp table named `recruiters` (which lives for the pooled connection) could otherwise grant a recruiter every region. | User (approved hardening) |
| D35 | Lint & format | Backend: ruff (`backend/ruff.toml`: E,F,W,I,B,UP,SIM; E501 left to the formatter; SIM117 off in tests) — `ruff check .` and `ruff format --check .`. Frontend: ESLint 9 (typescript-eslint recommended + react-hooks) and `tsc -b` via `npm run lint`; Prettier (printWidth 100) via `npm run format:check`. | Claude's call (user asked for lint + format checks) |

## 3. Row-by-row audit and expected outcome (candidates_import.csv)
| Row | ID | Issue | Outcome |
|---|---|---|---|
| 2 | C-1001 | same email as row 33 | dropped, **merged** into row 33 (D2) |
| 5 | C-1004 | exact duplicate of row 32 | dropped, **merged** (D3) |
| 17 | C-1016 | same email as row 34 | dropped, **merged** into row 34 (D2) |
| 2,4,10,15,17,21,24,27,30 | — | salary `$95,000` / `97,500` | → integer |
| 7,9,11,16,45,46 | — | Unicode names | kept NFC, must render |
| 32 | C-1004 | exact duplicate | imported (survivor) |
| 33 | C-1031 | email `  Alicia.Trent@Gmail.com ` | normalized; imported (survivor) |
| 34 | C-1032 | `A. Diallo`, different phone/salary/date | imported (survivor) |
| 35 | C-1033 | `marcus.reed[at]gmail.com` | **reject** invalid email |
| 36 | C-1034 | no `@` | **reject** invalid email |
| 37 | C-1035 | email empty | **reject** email required |
| 38 | C-1036 | `O'Connor'); DROP TABLE candidates;--` | **reject** invalid name characters |
| 39 | C-1037 | notes `' OR '1'='1` | imported, stored literally |
| 40 | C-1038 | `06/30/2026` | → 2026-06-30 |
| 41 | C-1039 | `14-May-2026` | → 2026-05-14 |
| 42 | C-1040 | `2026-02-30` | **reject** impossible date |
| 43 | C-1041 | date empty | **reject** date required |
| 44 | C-1042 | `us-mw` | → US-MW |
| 45 | C-1043 | ` CO-BOG ` | → CO-BOG |
| 46 | C-1044 | `USW` | → US-W |
| 47 | C-1045 | `ZZ-99` | **reject** unknown region |
| 48 | C-1046 | `ACTIVE`, `85k` | → active, 85000 |
| 49 | C-1047 | `actve`, `negotiable` | **reject** invalid status (salary would be null) |
| 50 | C-1048 | `on hold`, salary empty | → on_hold, null |
| 51 | C-1049 | quoted comma in notes | kept |
| 52 | C-1050 | multi-line notes | kept verbatim |
| 53 | C-1010 | id collision with row 11, different email | **reject** (D4) |
| 54 | C-1051 | region empty, phone empty | **reject** region required |

**Expected report on a fresh DB:** imported 40, merged 3, rejected 10
(rows 35, 36, 37, 38, 42, 43, 47, 49, 53, 54), warnings 0.

## 4. recruiters.csv audit
Clean. R-101 Dana Whitmore admin `*`; R-102 Caleb Nguyen US-MW|US-NE; R-103 Marisol Vega
PH-MNL|CO-BOG; R-104 Jordan Blake US-W|US-SE; R-105 Tessa Iqbal US-NE. All regions canonical,
all six covered, US-NE shared by Caleb and Tessa.

## 5. Required tests (minimum from brief)
Dedup (rows 2/33, 17/34, 5/32), invalid email (35/36/37), injection rows (38 rejected with
tables intact; 39 stored byte-exact), Caleb cannot fetch a PH-MNL candidate, Dana can,
unknown recruiter → 403, full-file report equals §3 expected counts.

## 6. Work log
- 2026-10-21 — Scoping: byte-level audit of both CSVs, decisions D1–D19 agreed. No code yet.
- 2026-10-21 — Implementation plan written: `docs/superpowers/plans/2026-10-21-techforce-take-home.md` (Tasks 0–8; proposes D20–D27, added in Task 0).
- 2026-10-21 — Task 0: `.gitignore`, decisions D20–D27 recorded, source CSVs + plan committed. Work happens on `main` (empty repo, user asked for commits there). User rule: no Co-Authored-By/AI trailer in commit messages.
- 2026-10-21 — Task 1: docker-compose (db + api), `db/init/01-roles.sh` creates `techforce_app` (NOSUPERUSER, NOBYPASSRLS) and `techforce_test` DB; FastAPI skeleton with `/healthz`; `pytest.ini` sets `pythonpath = .` and silences one third-party starlette/anyio DeprecationWarning. Tests: `docker compose run --rm api pytest -q` → 1 passed.
- 2026-10-21 — D28: source CSVs and brief PDF git-ignored and untracked (user). They remain in commit 6e712a3's history.
- 2026-10-21 — Task 2: `app/importer/normalize.py` field normalizers (D6–D13). Salary accepts only well-formed thousands grouping (`1,2,3` → null + warning) and a whole-number result (`85.5` → null + warning). Email returns email-validator's normalized form of the lowercased input. → 56 passed.
- 2026-10-21 — Task 3: `CandidateIn` Pydantic model + `pipeline.parse_csv/build_plan`. Real file → 40 survivors, merges (2→33, 5→32, 17→34), rejected rows 35,36,37,38,42,43,47,49,53,54 with all field errors per row. Blank lines skipped (row numbers still count them); empty file → FileError. An invalid later duplicate never supersedes a valid earlier row; a superseded row's salary warning is dropped. → 71 passed.
- 2026-10-21 — Task 4: `schema.sql` (tables, CHECK constraints for regions/status, RLS ENABLE+FORCE, `app_can_see(region)`, SELECT/INSERT/UPDATE policies for `techforce_app`, no DELETE grant), `db.scoped()` sets `app.recruiter_id` transaction-locally, `recruiters.py` strict roster load + seed; app startup migrates and reseeds. Tests prove scoping at the SQL level with no API code: no setting → 0 rows, Caleb → US-MW/US-NE, Marisol → PH-MNL/CO-BOG, Dana → all, pooled connection doesn't leak scope, out-of-scope INSERT blocked. → 90 passed.
- 2026-10-21 — Task 5: `POST /api/v1/candidates/import` (admin only, 5 MB cap → 413, FileError → 400). `repository.apply_plan` runs inside `scoped(admin)`: one SELECT for existing id/email collisions, then one `INSERT … ON CONFLICT (email) DO UPDATE … RETURNING (xmax = 0)` per 1000 rows. D5 corrected: re-import reports merged 43, not 40 (invariant imported+merged+rejected = 53). Live curl on dev DB → 40 / 3 / rejected rows 35,36,37,38,42,43,47,49,53,54; Caleb → 403. → 107 passed.
- 2026-10-21 — Task 6: `GET /api/v1/candidates` (search/status/page/page_size), `GET /api/v1/candidates/{id}` (404 "candidate not found" when out of scope), `GET /api/v1/recruiters` (unauthenticated roster for the switcher). No region predicate anywhere in Python; all reads in `scoped()`. Search also matches "first last" full name and is NFC-normalized. Live: Dana 40, Caleb 19, Marisol 9, Jordan 12, Tessa 8, R-999 → 403. → 133 passed.
- 2026-10-21 — Task 7: React 18 + Vite 5 + TS recruiter view (`frontend/`), pinned deps, `web` compose service (node:22-alpine, Vite proxy `/api` → api:8000). Recruiter switcher defaults to Caleb, 300 ms debounced search, status filter, pager; previous request aborted on change so stale data can't overwrite a switch; API errors shown in an alert. Midnight Minimalist styling (D29). vitest + testing-library: 4 tests (Caleb header, switch to Marisol shows "Nguyễn Thị Hoa", status param, 403 shown). `tsc -b && vite build` clean; checked visually with a headless Chrome screenshot.
- 2026-10-21 — Task 8: README (setup from clean machine, API table, RLS explanation) and NOTES.md (rules with row evidence, dedup rules, next steps; AI usage log left as TODO for the candidate to write personally). Clean check: `docker compose down -v && docker compose up -d --build`, README curl → 40/3/10; via UI proxy Caleb 19, Marisol 9, Dana 40. `docker compose run --rm api pytest -q` → 133 passed; `docker compose run --rm web npm test` → 4 passed.
- 2026-10-21 — Final review (fresh reviewer, Opus): no Critical. Fixed with tests RED→GREEN: huge salary 500 (→ null + warning, D11), stray quote silently swallowing rows and oversized cell 500 (strict csv → 400, D15), NUL byte 500 in import (→ 400) and in search/path (→ 422), huge page 500 (→ 422, D25). Deferred minors: UI double fetch on page reset, stale rows shown briefly on recruiter switch, shared error slot, check-then-upsert race between concurrent imports. → 146 passed.
- 2026-10-21 — Security review (fresh reviewer over 6e712a3..aa641cb): no Critical. Every finding re-verified with a test or probe. Fixed RED→GREEN: (1) unlimited body read before auth — refused callers' 50 MB body fully read (52/52 chunks) → now 0 chunks, D33; (2) DB-id-rejected winner dropped an earlier valid row and reported a phantom merge → D31; (3) recruiters removed from the roster kept access → D30; (4, upgraded from Minor) concurrent imports 500 with KeyError in 4/5 probe rounds; also found the async endpoint ran blocking DB work on the event loop → D32. Live: 100 MB upload as R-999/R-102 → 403 with 0 bytes sent, admin → 413; re-import still 0/43/10. Playwright pass over the UI: Caleb 19 (US-MW/US-NE), Marisol 9, Dana 40 over 2 pages, Unicode renders, hostile search terms → 0 rows/422, header sent per switch. Minors verified but not fixed (await user): temp-table shadowing of `recruiters` in `app_can_see` (persists on the pooled connection), duplicate X-Recruiter-Id first-wins, non-ASCII digits/long-s accepted by normalizers, punctuation-only names, year-0001 dates, owner role is superuser, no DB CHECKs mirroring D6/D7/D12. → 155 passed.
- 2026-10-21 — Committed review fixes (cba148e, 978a71f, 58c518c). D34: RLS hardening test-first — RED showed Caleb seeing all 6 regions through a shadowing temp table; now app role gets "permission denied to create temporary tables" and the function ignores a shadow even with TEMP granted. Dev DB re-migrated (API restart); counts unchanged 40/19/9. → 157 passed.
- 2026-10-21 — D10 revised + ASCII-only codes (D8, D11, D12), test-first: 11 RED (ambiguous slash dates, unpadded ISO, Arabic-Indic digits in id/date/salary, long-s region, year 0001/1999/next+1) → GREEN. Real file still 40/3/10 (only slash date is row 40's unambiguous 06/30). UI: dates, region codes and status pills no longer wrap at the hyphen (checked in Playwright at 825px). → 173 passed; frontend 4 passed, build clean.
- 2026-10-21 — Committed D10/ASCII (cdb4fc0) and UI no-wrap (126f2ce). Wrote §7 (review triage, Playwright pass, decision re-review, open backlog, gotchas).

## 7. Security review and decision re-review (2026-10-21)

### 7.1 Process
1. A fresh reviewer subagent was given the brief, this file and the source CSVs, and reviewed 6e712a3..aa641cb with a security focus: RLS, injection, header handling, validation, DB constraints and merge correctness. It ran probes only against `techforce_test`.
2. Every finding was re-verified with a failing test or a probe before being accepted. Fixes were made test-first (RED shown, then GREEN). No finding was taken on the reviewer's word.
3. A Playwright pass over the running app ran in parallel with the review.

### 7.2 Findings triage
| # | Reviewer severity | Finding | Verification | Disposition |
|---|---|---|---|---|
| 1 | Important | The multipart body was read before the admin check, with no transport cap | ASGI test: a refused caller had 52/52 one-MB chunks pulled before the 403. Live 200 MB repro by the reviewer | **Fixed** (D33). Now 0 chunks read. Live 100 MB as R-999/R-102 → 403 with 0 bytes sent; admin → 413 |
| 2 | Important | A winner rejected for a DB candidate_id collision had already superseded an earlier valid row → data lost and the report showed a phantom merge | API test: report `(0 imported, 1 merged)`, nothing stored for the email | **Fixed** (D31) |
| 3 | Important | Recruiters removed from recruiters.csv kept their row and access | Seed test: R-900 admin survived a reseed | **Fixed** (D30) |
| 11 | Minor → **raised to Important** | Concurrent imports race between the snapshot and the upsert | Probe: `KeyError` 500 in 4 of 5 rounds. Also found the async endpoint ran blocking DB work on the event loop | **Fixed** (D32) |
| 4 | Minor | A temp table named `recruiters` shadows the real one inside `app_can_see` | Probe: Caleb went from 0 to 1 PH-MNL row. Also found the shadow **persists on the pooled connection**: it broke `get_recruiter` for the next request on that connection | **Fixed** (D34, user-approved hardening) |
| 5 | Minor | Non-ASCII lookalikes normalize to valid values (`C-١٢٣٤`, `uſ-mw`, Arabic-Indic digits in dates and salaries; the Kelvin sign in email folds to `k`) | Probe confirmed each case | **Fixed** for ID, region, date and salary (D8/D10/D11/D12). Email left as is: internationalized addresses are legitimate (D7) |
| 6 | Minor | Lax values: name `.`/`-'`/a lone combining mark; dates `0001-01-01`, `2026-1-5` | Probe confirmed | Dates **fixed** (D10). Names **deferred** (D6 change not yet approved) |
| 7 | Minor | Duplicate `X-Recruiter-Id` headers: the first one wins | Probe: `R-102, R-999` → 200 (should be 403) | **Open**, not yet approved |
| 8 | Minor | `techforce_owner` is the image superuser; hard-coded dev passwords; port 5432 published; password interpolated into SQL in `01-roles.sh` | Probe: `rolsuper = true` | **Open**. Acceptable for dev, but should be stated in README |
| 9 | Minor | No DB CHECKs mirroring D6/D7/D12 (lowercase email, ID format, non-blank names); email uniqueness is case-sensitive | Read from schema.sql | **Open** (hardening, not yet done) |
| 10 | Minor | `GET /api/v1/recruiters` is unauthenticated and reveals the admin ID | Probe: 200 with no header | **Accepted** as inherent to the brief's header-only identity; should get a NOTES line |
| 12 | Minor | NOTES AI usage log is still TODO | — | **Left for the candidate** (must be written personally) |

The reviewer's "Declined to judge" items were accepted as out of scope: upsert vs. an out-of-scope row (only admins import), count/page skew under READ COMMITTED, CSV formula injection (no CSV output), D27 itself, the already-deferred UI minors, rate limiting, `app_can_see` not leakproof (not a leak), and ilike performance.

### 7.3 Playwright pass (UI at :5173 through the Vite proxy)
- Default view is Caleb: 19 rows, only US-MW/US-NE, "Scope: US-MW, US-NE".
- Marisol: 9 rows, CO-BOG/PH-MNL. Unicode names render correctly (Lucía, Sofía, Nguyễn Thị Hoa, Tomás).
- Dana: 40 rows over 2 pages (25 + 15), all 6 regions.
- The switcher sends `x-recruiter-id` on every request (seen in the request headers).
- Search: `nguyễn` → 1 row. `%`, `_`, `\`, `' OR '1'='1`, `'); DROP TABLE…`, `<img onerror>` → 0 rows with 200. 201 characters or a NUL → 422.
- Headers: missing, empty, whitespace, `r-102` (wrong case), R-999 and injection-shaped IDs → 403. A padded `" R-102 "` → 200 only because browsers strip header whitespace before sending.
- Detail endpoint: Caleb on a PH-MNL ID → 404; Dana → 200; Marisol on a US-MW ID → 404; unknown recruiter → 403.
- Import: no header / R-999 → 403 "unknown recruiter", R-102 → 403 "admin only", bad header row → 400. Re-importing the real file → 0/43/10.
- Observed, not fixed:
  - Two requests aborted on load (React StrictMode dev double-mount; the abort controller handles it).
  - favicon 404.
  - The known double fetch when switching recruiter on page 2.
  - One "Next" click that did nothing; it could not be reproduced on retry.
- Fixed: dates and region codes wrapped at the hyphen at 825px → `white-space: nowrap` (126f2ce). Verified with a line-box check and a screenshot.

### 7.4 Senior re-review of the decision log, with the user's rulings
| Item | Recommendation | User ruling |
|---|---|---|
| D10 slash dates | MM/DD is a guess for Bogotá/Manila sources; reject when both readings are valid and differ. Add a 2000→next-year range and exact ASCII shapes | **Approved, done** |
| D8/D11/D12 ASCII | Require ASCII before case-mapping or matching | **Approved, done** |
| `app_can_see` hardening | Schema-qualify, pin `search_path`, revoke TEMP | **Approved, done** (D34) |
| UI date wrapping | nowrap | **Approved, done** |
| D2 candidate_id churn | The winner replaces the ID, so a stored C-1001 can become C-1031 on re-import. Keep the earliest ID and take the details from the last row | Deferred: changes expected report/tests; mention in NOTES next steps |
| D5/D16 `updated` count | "merged" mixes in-file duplicates with DB updates (re-import says merged 43). Add `updated` | Deferred: note in NOTES |
| D6 names | Require at least one letter; consider allowing an empty last name (mononyms) | Not yet approved |
| Duplicate header | More than one `X-Recruiter-Id` → 403 | Not yet approved |
| DB CHECKs, non-superuser owner | Defence in depth | Not yet approved |
| D11 currency | Salaries have no currency, so cross-region figures aren't comparable | Note only |
| Keep as is | D1, D3, D4, D7, D9, D13–D15, D17–D30. D21 (403 for a missing header) matches the brief over 401 convention. D22's 404 doesn't leak existence. D27 is conservative but explicit and consistent | — |

### 7.5 Open backlog
1. Reject duplicate `X-Recruiter-Id` headers.
2. D6: names must contain at least one letter.
3. DB CHECKs: `email = lower(email)`, `candidate_id ~ '^C-[0-9]{4}$'`, non-blank names, applied_date range.
4. Non-superuser schema owner; README "Security model and limits" section (trusted header, trusted app role, dev passwords, upload cap, unauthenticated roster).
5. NOTES next steps: D2 ID preservation, `updated` count, salary currency.
6. UI minors: double fetch on page reset, stale rows on switch, shared error slot, favicon.
7. NOTES AI usage log (candidate). Material from this review: the phantom merge, the upload read before auth, and the concurrency test that passed for the wrong reason.

### 7.6 Gotchas learned
- **FastAPI reads declared body parameters (`UploadFile`, `Form`) before running dependencies**, so auth in `Depends` doesn't protect against large uploads. Take `Request` and parse after auth.
- **Starlette's form parser returns `starlette.datastructures.UploadFile`**; FastAPI's `UploadFile` is a subclass, so `isinstance` against FastAPI's class fails.
- **An entered `with TestClient(app)` runs requests on one portal/event loop.** Together with an `async def` endpoint doing blocking DB work, that serialized "concurrent" requests and hid the race. Use one un-entered client per thread to really overlap requests.
- **Postgres temp tables live for the session, not the transaction**, so with pooling one shadowing table affects later requests on that connection.
- **psycopg treats `%` in `exec_driver_sql` text as a placeholder**: `format('%I', …)` in schema.sql fails, so use `quote_ident(...)`.
- **schema.sql is applied only at API startup**: uvicorn `--reload` watches `.py` files, so restart `api` after editing SQL.
- **Browsers strip leading/trailing whitespace from header values**, so padded-header tests must use a raw client, not `fetch`.
- 2026-10-21 — D35: added ruff (backend) and ESLint + Prettier (frontend); fixed 3 lint findings (zip strict, import order, yoda) and applied both formatters — no behaviour change (173 / 4 passed). CLAUDE.md re-synced with code: D14 (current import flow incl. DB claims + advisory lock), D16 (merges in report), D18 (set_config, not SET LOCAL), D19, D25 (full-name match, NFC), D27 moved into order. Note: work-log entries above describe the code as it was at that point (e.g. `apply_plan` is now `import_rows`).
- 2026-10-21 — README rewritten (clean setup, commands incl. lint/format, API + parameter tables, scoping, layout, troubleshooting). NOTES.md rewritten to one page with the agreed rules and an AI usage log drawn from this record (user asked Claude to write it from the real events).
