"""Field-level rules (CLAUDE.md D6-D13). Inputs are the literal values from the audit."""
import unicodedata
from datetime import date

import pytest

from app.importer.normalize import (
    REGIONS,
    STATUSES,
    clean_optional,
    normalize_candidate_id,
    normalize_email,
    normalize_name,
    normalize_region,
    normalize_status,
    parse_date,
    parse_salary,
)


def test_canonical_sets():
    assert REGIONS == {"US-MW", "US-NE", "US-SE", "US-W", "PH-MNL", "CO-BOG"}
    assert STATUSES == ("active", "screening", "interviewing", "withdrawn", "on_hold")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("alicia.trent@gmail.com", "alicia.trent@gmail.com"),
        ("  Alicia.Trent@Gmail.com ", "alicia.trent@gmail.com"),
    ],
)
def test_email_normalized(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize(
    "raw, message",
    [
        ("marcus.reed[at]gmail.com", "invalid address 'marcus.reed[at]gmail.com'"),
        ("tina.holloway.gmail.com", "invalid address 'tina.holloway.gmail.com'"),
        ("", "required"),
        ("   ", "required"),
    ],
)
def test_email_rejected(raw, message):
    with pytest.raises(ValueError) as exc:
        normalize_email(raw)
    assert str(exc.value) == message


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("US-MW", "US-MW"),
        ("us-mw", "US-MW"),
        (" CO-BOG ", "CO-BOG"),
        ("USW", "US-W"),
        ("phmnl", "PH-MNL"),
    ],
)
def test_region_normalized(raw, expected):
    assert normalize_region(raw) == expected


@pytest.mark.parametrize(
    "raw, message",
    [
        ("ZZ-99", "unknown region 'ZZ-99'"),
        ("US_W", "unknown region 'US_W'"),
        ("US-WEST", "unknown region 'US-WEST'"),
        ("", "required"),
    ],
)
def test_region_rejected(raw, message):
    with pytest.raises(ValueError) as exc:
        normalize_region(raw)
    assert str(exc.value) == message


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Active", "active"),
        ("ACTIVE", "active"),
        ("on hold", "on_hold"),
        ("On-Hold", "on_hold"),
        (" Interviewing ", "interviewing"),
    ],
)
def test_status_normalized(raw, expected):
    assert normalize_status(raw) == expected


@pytest.mark.parametrize(
    "raw, message",
    [("actve", "unknown status 'actve'"), ("", "required")],
)
def test_status_rejected(raw, message):
    with pytest.raises(ValueError) as exc:
        normalize_status(raw)
    assert str(exc.value) == message


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-05-14", date(2026, 5, 14)),
        ("06/30/2026", date(2026, 6, 30)),
        ("14-May-2026", date(2026, 5, 14)),
        ("14-MAY-2026", date(2026, 5, 14)),
    ],
)
def test_date_parsed(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    "raw, message",
    [
        ("2026-02-30", "not a valid date '2026-02-30'"),
        ("30/06/2026", "not a valid date '30/06/2026'"),
        ("May 14 2026", "not a valid date 'May 14 2026'"),
        ("", "required"),
    ],
)
def test_date_rejected(raw, message):
    with pytest.raises(ValueError) as exc:
        parse_date(raw)
    assert str(exc.value) == message


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("$95,000", (95000, None)),
        ("97,500", (97500, None)),
        ("88000", (88000, None)),
        ("85k", (85000, None)),
        ("$1.5K", (1500, None)),
        ("", (None, None)),
    ],
)
def test_salary_parsed(raw, expected):
    assert parse_salary(raw) == expected


@pytest.mark.parametrize("raw", ["negotiable", "-5", "1,2,3", "85.5", "$"])
def test_salary_unparseable_is_null_with_warning(raw):
    assert parse_salary(raw) == (None, f"salary '{raw}' is not numeric; stored as null")


@pytest.mark.parametrize(
    "raw", ["Nguyễn", "Thị Hoa", "A.", "O'Connor", "O’Connor", "Castellanos-Ruiz"]
)
def test_name_allowed(raw):
    assert normalize_name(raw) == raw


def test_name_trimmed_and_nfc():
    nfd = unicodedata.normalize("NFD", "Tomás")
    assert nfd != "Tomás"
    assert normalize_name(f"  {nfd} ") == "Tomás"


@pytest.mark.parametrize(
    "raw", ["O'Connor'); DROP TABLE candidates;--", "Bob<script>", "R2D2"]
)
def test_name_rejected(raw):
    with pytest.raises(ValueError) as exc:
        normalize_name(raw)
    assert str(exc.value) == (
        "contains characters other than letters, spaces, apostrophes, hyphens or periods"
    )


def test_name_required():
    with pytest.raises(ValueError, match="^required$"):
        normalize_name("  ")


def test_candidate_id():
    assert normalize_candidate_id(" C-1001 ") == "C-1001"
    with pytest.raises(ValueError, match=r"^must match C-#### \(got '1001'\)$"):
        normalize_candidate_id("1001")
    with pytest.raises(ValueError, match="^required$"):
        normalize_candidate_id("")


def test_clean_optional_keeps_text_verbatim():
    assert clean_optional("  ") is None
    assert clean_optional(" ' OR '1'='1 ") == "' OR '1'='1"
    assert clean_optional("Round 1 passed.\nRound 2 pending.") == "Round 1 passed.\nRound 2 pending."


@pytest.mark.parametrize("raw", ["99999999999", "3000000k", "$2,147,483,648"])
def test_salary_beyond_integer_column_is_null_with_warning(raw):
    assert parse_salary(raw) == (None, f"salary '{raw}' is not numeric; stored as null")


def test_salary_at_integer_max_is_kept():
    assert parse_salary("2147483647") == (2147483647, None)
