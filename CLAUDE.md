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
| D5 | Re-import / existing DB rows | DB rows are "earlier" than the file → file row overwrites by email (upsert). Re-importing the same file: imported 0, merged = all. | Claude's call |
| D6 | Names | Required, trimmed, NFC. Allowlist: Unicode letters, combining marks, space, `'`, `’`, `-`, `.`. Anything else → reject. Row 38 (`O'Connor'); DROP TABLE…`) rejected by this rule. | User |
| D7 | Email | Required. Trim + lowercase whole address; syntax check with email-validator (no DNS). No de-obfuscation of `[at]`. | Claude (brief) |
| D8 | Region | Required. Trim + uppercase; exact match to US-MW, US-NE, US-SE, US-W, PH-MNL, CO-BOG; or, if no hyphen, exact match against codes with hyphen removed (USW→US-W). Anything else → reject. | User (USW) |
| D9 | Status enum | `active, screening, interviewing, withdrawn, on_hold`. Input trimmed, lowercased, spaces/hyphens → `_`, then exact match. `actve` → reject. | User |
| D10 | applied_date | Required. Accept `YYYY-MM-DD`, `MM/DD/YYYY` (US order), `DD-Mon-YYYY` (English month abbrev, case-insensitive). Must be a real calendar date; impossible → reject. Stored as DATE. | User |
| D11 | Salary | Optional. Strip `$`, `,`, whitespace; optional trailing `k`/`K` ×1000; must yield a non-negative whole number. Empty → null. Unparseable (`negotiable`) → null + warning (never rejects the row alone). No currency stored. | User (85k) |
| D12 | candidate_id | Required, trimmed, must match `C-\d{4}`. | Claude's call |
| D13 | Phone, source, notes | Optional, trimmed, stored verbatim (notes keep newlines). Hostile text (row 39 `' OR '1'='1`) stored literally. | Claude's call |
| D14 | Pipeline order | Parse → validate each row (collect **all** field errors into the reason) → dedup valid rows → one batched upsert in a single transaction. | Claude's call |
| D15 | File-level checks | Must be UTF-8 (BOM stripped); header must equal the 12 expected columns, else HTTP 400. Rows with wrong field count → rejected. | Claude's call |
| D16 | Report shape | `{imported, merged, rejected:[{row, candidate_id, reason}], warnings:[{row, candidate_id, message}]}` | Claude's call |
| D17 | Recruiters | Seeded from recruiters.csv. `*` must be the sole token and iff role=admin; unknown region fails the seed. | Claude's call |
| D18 | Authorization | Postgres Row-Level Security with a non-superuser app role; per-request `SET LOCAL app.recruiter_id`; policy joins recruiter regions; admins bypass via policy. Unknown X-Recruiter-Id → 403 before querying. | Claude's call |
| D19 | Stack | FastAPI, Pydantic v2, SQLAlchemy 2 + psycopg, Postgres 16 in docker-compose; React + Vite + TS; pytest against real Postgres. | Claude's call |
| D20 | Import auth | `POST /import` requires an admin `X-Recruiter-Id`; non-admin or unknown → 403. | Claude's call |
| D21 | Missing header | Missing `X-Recruiter-Id` → 403 (same as unknown), not FastAPI's 422. | Claude's call |
| D22 | Single fetch | `GET /api/v1/candidates/{candidate_id}` out of scope → 404 (RLS makes it invisible; existence not leaked). | Claude's call |
| D23 | Merge detail | Report adds `merges: [{row, candidate_id, kept_row}]` — one entry per superseded record: `row`/`candidate_id` = what was dropped, `kept_row` = file row that won; `row` null when the dropped record was already in the DB. | Claude's call |
| D24 | Pagination | `page` ≥1 (default 1), `page_size` 1–100 (default 25); response `{items, total, page, page_size}`; order `applied_date DESC, candidate_id ASC`. | Claude's call |
| D25 | Search | Case-insensitive substring over first_name, last_name, email, desired_role; `%`, `_`, `\` escaped (literal); `status` must be in enum else 422. | Claude's call |
| D26 | Brief PDF | Not committed (company document); `.gitignore` excludes `*.pdf`. | Claude's call |
| D28 | Source files in git | `candidates_import.csv`, `recruiters.csv` and the brief PDF are git-ignored and untracked; they stay on disk at the repo root and are mounted into the API container at `/data/`. README must tell a reader to place them there. | User |
| D27 | ID claim | The first valid row to use a candidate_id owns it for the whole import; a later row with that id and a different email is rejected (D4), even if the owner is later superseded by email. | Claude's call |

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

