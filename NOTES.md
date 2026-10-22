# NOTES

Full decision record with row evidence: `CLAUDE.md` (D1–D35). Rows are numbered like a
spreadsheet (header = row 1).

## Normalization (reject with a reason rather than guess, no fuzzy matching)

A row is valid only if every required field passes. The rejection reason lists **every**
failing field. Codes, IDs, dates and salaries must be ASCII, so lookalike characters (`uſ-mw`,
Arabic-Indic digits) can never normalize into a valid value.

| Field | Rule | Evidence |
|---|---|---|
| email | required; trim + lowercase; syntax check, no DNS; `[at]` not decoded | ` Alicia.Trent@Gmail.com ` normalized (33); `[at]` (35), no `@` (36), empty (37) rejected |
| region | trim, uppercase, exact match to the 6 codes or the code minus its hyphen | `us-mw` (44), ` CO-BOG ` (45), `USW`→`US-W` (46); `ZZ-99` (47), empty (54) rejected |
| status | `active, screening, interviewing, withdrawn, on_hold`, case-insensitive exact | `ACTIVE` (48), `on hold` (50); `actve` (49) rejected |
| date | `YYYY-MM-DD`, `MM/DD/YYYY`, `DD-Mon-YYYY`; real date 2000 to next year; a slash date that reads differently as MM/DD and DD/MM is rejected as ambiguous | `06/30/2026` (40), `14-May-2026` (41); `2026-02-30` (42), empty (43) rejected |
| salary | `$`, `,`, `k` understood; whole number 0–2,147,483,647, otherwise null + warning | `$95,000`, `97,500`, `85k` (48); `negotiable` → null |
| names | NFC; letters/marks, space, `'` `’` `-` `.` only | `Nguyễn Thị Hoa` kept; `O'Connor'); DROP TABLE…` (38) rejected |
| free text | stored verbatim (newlines kept) | `' OR '1'='1` (39) stored literally |

## Dedup / merge rules

1. Validate first; only valid rows take part in dedup.
2. **Identity is the normalized email. The last occurrence wins** and replaces the whole
   record, including `candidate_id`. Merged: 2→33, 17→34 ("A. Diallo" wins), exact
   duplicate 5→32.
3. **Same ID with a different email is a different person.** The first claimant keeps the ID
   and the later row is rejected (53: C-1010 Becca vs Sofía). IDs already in the DB are the
   earliest claims and are checked before dedup.
4. DB rows count as earlier than the file, so a re-import upserts by email. The invariant
   `imported + merged + rejected = rows` holds: 40+3+10 the first time, 0+43+10 on re-import.
5. Parameterized SQLAlchemy Core only. One transaction, an advisory lock, and one multi-row
   `INSERT … ON CONFLICT` per 1000 rows.

## AI usage log (Claude Code)

**Delegated:** the byte-level CSV audit (record count via `csv`, not lines), the implementation
plan, test-first implementation task by task, two fresh-context code reviews, and lint/format
setup. Every decision went into CLAUDE.md as it was made.

**Decisions I made myself.** Several of these overrode the AI's recommendation:
- **Merge winner:** last occurrence wins (the AI recommended first in file).
- **Hostile name in row 38:** rejected via a character allowlist (the AI recommended storing
  it verbatim).
- **Borderline values:** `USW` and US-order dates are accepted (the AI recommended rejecting
  both). I later tightened slash dates so ambiguous ones are rejected.
- **Statuses:** `on_hold` added to the enum.
- **Repo contents:** client CSVs and the brief stay out of git.
- **UI and security:** the dark UI style, and approval of the RLS hardening.

**Mistakes I caught and corrected:**
- **Row numbering:** the AI cited "rows 33 and 34" with the header counted as row 1, without
  saying so. In my count those rows had different emails. I flagged it, and the convention is
  now explicit (D1), with `candidate_id` in every report entry.
- **Client data in git:** the first commit included the client CSVs. I had them untracked
  and git-ignored. They still exist in that commit's history.
- **Commit attribution:** the AI added a `Co-Authored-By` AI trailer to commit messages. I
  rejected it.

**Found by the tests and reviews I asked for:**
- **Re-import count:** the AI's own plan said a re-import gives merged 40. The test showed
  43, which is correct.
- **Bugs the reviews found:** a huge salary caused a 500; a stray quote silently swallowed
  rows; uploads were read before the auth check; a temp table named `recruiters` could bypass
  RLS; recruiters removed from the roster kept their access. Each was fixed test-first.

## Next steps

Accent-insensitive search (`unaccent`), real authentication in place of the trusted header,
an import audit table with dry-run mode, background jobs for large files, and a queue for
fixing and re-submitting rejected rows.
