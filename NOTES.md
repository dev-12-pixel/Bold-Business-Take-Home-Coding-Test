# NOTES

Full decision record with row-level evidence: `CLAUDE.md` (D1–D29). Summary below.

## Validation & normalization

A row is valid only if **every** required field passes; the rejection reason lists every
failing field. Rows are numbered like a spreadsheet (header = row 1). I reject with a reason
rather than guess, and there's no fuzzy matching anywhere.

| Field | Rule | Evidence |
|---|---|---|
| email | required; trim + lowercase; syntax check (no DNS); no de-obfuscation | `  Alicia.Trent@Gmail.com ` → normalized (row 33); `[at]` (35), no `@` (36), empty (37) → rejected |
| region | trim + uppercase, exact match to the 6 codes, or the code with its hyphen removed | `us-mw` (44), ` CO-BOG ` (45), `USW` → `US-W` (46); `ZZ-99` (47), empty (54) → rejected |
| status | enum `active, screening, interviewing, withdrawn, on_hold`; case-insensitive exact match | `ACTIVE` (48), `on hold` → `on_hold` (50); `actve` (49) → rejected |
| applied_date | required; `YYYY-MM-DD`, `MM/DD/YYYY`, `DD-Mon-YYYY`; must be a real date | `06/30/2026` (40), `14-May-2026` (41); `2026-02-30` (42), empty (43) → rejected |
| salary | `$`, `,` and `k` understood; must be a whole non-negative number, else **null + warning** (never rejects a row on its own) | `$95,000`, `97,500`, `85k` (48); `negotiable` → null |
| names | required, NFC; Unicode letters/marks, space, `'` `’` `-` `.` only | `Nguyễn Thị Hoa` kept; `O'Connor'); DROP TABLE…` (38) → rejected |
| free text | phone/role/source/notes stored verbatim (newlines kept) | `' OR '1'='1` (39) stored literally |

## Dedup / merge rules

1. Validate first, then dedup only the valid rows.
2. **Identity = normalized email. The last occurrence in the file wins**: it replaces the whole
   record, including `candidate_id`. Rows 2→33 (Alicia), 17→34 (Amara/"A."), and the exact
   duplicate 5→32 are reported as `merged`.
3. **Same `candidate_id`, different email** = a different person, not a merge. The first row
   to claim the ID keeps it and the later row is rejected (row 53, C-1010 Becca vs Sofía).
4. Records already in the database count as earlier than the file, so re-importing upserts by
   email. Invariant: `imported + merged + rejected = rows in the file` (first import 40+3+10,
   re-import 0+43+10).
5. SQL injection: parameterized SQLAlchemy Core only. Writes are one transaction: one
   collision SELECT plus one multi-row `INSERT … ON CONFLICT` per 1000 rows (a test asserts
   exactly one INSERT for the real file).

## AI usage log

> **TODO (candidate):** fill this in yourself. It has to reflect your own experience.

- **Delegated to the AI:**
- **Deliberately did not delegate:**
- **Something the AI got wrong that I caught and corrected:**

## Next steps

- Accent-insensitive search (`unaccent` plus a trigram index) so "Tomas" finds "Tomás".
- Real authentication (signed sessions/JWT) in place of the trusted `X-Recruiter-Id` header.
- An import audit table (who imported what and when, with the stored report), plus a
  dry-run mode.
- Stream large files and run imports as background jobs. The 5 MB cap is a placeholder.
- A review queue so rejected rows can be fixed and re-submitted.
