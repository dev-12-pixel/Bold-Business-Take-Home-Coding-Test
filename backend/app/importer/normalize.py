"""Field normalizers for the candidate import (CLAUDE.md D6-D13).

Every function either returns the canonical value or raises ValueError with a
short message; the pipeline prefixes it with the field name. Nothing here
guesses: a value either matches an explicit rule or is rejected.
"""
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal

from email_validator import EmailNotValidError, validate_email

REGIONS = frozenset({"US-MW", "US-NE", "US-SE", "US-W", "PH-MNL", "CO-BOG"})
STATUSES = ("active", "screening", "interviewing", "withdrawn", "on_hold")

# Region codes with the hyphen removed, for inputs like "USW" (D8). Each key
# maps to exactly one canonical code, so this is a lookup, not a fuzzy match.
_REGIONS_WITHOUT_HYPHEN = {code.replace("-", ""): code for code in REGIONS}

# Tried in order; %b is the C-locale English month abbreviation (D10).
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y")

_CANDIDATE_ID = re.compile(r"C-\d{4}")
_NAME_PUNCTUATION = frozenset(" '’-.")
_SALARY = re.compile(r"\$?(?P<number>\d{1,3}(?:,\d{3})+|\d+)(?P<fraction>\.\d+)?(?P<k>[kK])?")


def _required(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("required")
    return value


def normalize_candidate_id(raw: str) -> str:
    value = _required(raw)
    if not _CANDIDATE_ID.fullmatch(value):
        raise ValueError(f"must match C-#### (got '{value}')")
    return value


def normalize_name(raw: str) -> str:
    value = unicodedata.normalize("NFC", _required(raw))
    for char in value:
        if unicodedata.category(char)[0] not in "LM" and char not in _NAME_PUNCTUATION:
            raise ValueError(
                "contains characters other than letters, spaces, apostrophes, hyphens or periods"
            )
    return value


def normalize_email(raw: str) -> str:
    value = _required(raw).lower()
    try:
        return validate_email(value, check_deliverability=False).normalized
    except EmailNotValidError:
        raise ValueError(f"invalid address '{value}'") from None


def normalize_region(raw: str) -> str:
    value = _required(raw).upper()
    if value in REGIONS:
        return value
    if "-" not in value and value in _REGIONS_WITHOUT_HYPHEN:
        return _REGIONS_WITHOUT_HYPHEN[value]
    raise ValueError(f"unknown region '{raw.strip()}'")


def normalize_status(raw: str) -> str:
    value = re.sub(r"[\s-]+", "_", _required(raw).lower())
    if value not in STATUSES:
        raise ValueError(f"unknown status '{raw.strip()}'")
    return value


def parse_date(raw: str) -> date:
    value = _required(raw)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a valid date '{value}'")


def parse_salary(raw: str) -> tuple[int | None, str | None]:
    """Return (salary, warning). Never rejects the row (D11)."""
    compact = re.sub(r"\s+", "", raw)
    if not compact:
        return None, None
    match = _SALARY.fullmatch(compact)
    if match:
        amount = Decimal(match["number"].replace(",", "") + (match["fraction"] or ""))
        if match["k"]:
            amount *= 1000
        if amount == amount.to_integral_value():
            return int(amount), None
    return None, f"salary '{raw}' is not numeric; stored as null"


def clean_optional(raw: str) -> str | None:
    value = raw.strip()
    return value or None
