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
MAX_SALARY = 2_147_483_647  # Postgres integer column

# Region codes with the hyphen removed, for inputs like "USW" (D8). Each key
# maps to exactly one canonical code, so this is a lookup, not a fuzzy match.
_REGIONS_WITHOUT_HYPHEN = {code.replace("-", ""): code for code in REGIONS}

# Exact ASCII shapes (D10); strptime alone would accept "2026-1-5" and non-ASCII digits.
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_SLASH_DATE = re.compile(r"(?P<first>[0-9]{1,2})/(?P<second>[0-9]{1,2})/[0-9]{4}")
_MONTH_DATE = re.compile(r"[0-9]{1,2}-[A-Za-z]{3}-[0-9]{4}")  # %b: C-locale English abbrev
MIN_APPLIED_DATE = date(2000, 1, 1)

_CANDIDATE_ID = re.compile(r"C-[0-9]{4}")
_NAME_PUNCTUATION = frozenset(" '’-.")
_SALARY = re.compile(
    r"\$?(?P<number>[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?P<fraction>\.[0-9]+)?(?P<k>[kK])?"
)


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
    value = _required(raw)
    # ASCII first: .upper() maps lookalikes such as "ſ" (long s) onto "S".
    value = value.upper() if value.isascii() else value
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


def _date_format(value: str) -> str | None:
    """The one strptime format whose exact shape `value` has (D10), else None."""
    if _ISO_DATE.fullmatch(value):
        return "%Y-%m-%d"
    if slash := _SLASH_DATE.fullmatch(value):
        first, second = int(slash["first"]), int(slash["second"])
        if first <= 12 and second <= 12 and first != second:
            raise ValueError(f"ambiguous date '{value}' (MM/DD or DD/MM); use YYYY-MM-DD")
        return "%m/%d/%Y"
    if _MONTH_DATE.fullmatch(value):
        return "%d-%b-%Y"
    return None


def parse_date(raw: str) -> date:
    value = _required(raw)
    fmt = _date_format(value)
    try:
        parsed = datetime.strptime(value, fmt).date() if fmt else None
    except ValueError:
        parsed = None
    if parsed is None:
        raise ValueError(f"not a valid date '{value}'")
    latest = date(date.today().year + 1, 12, 31)
    if not MIN_APPLIED_DATE <= parsed <= latest:
        raise ValueError(f"date '{value}' outside {MIN_APPLIED_DATE} to {latest}")
    return parsed


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
        if amount == amount.to_integral_value() and amount <= MAX_SALARY:
            return int(amount), None
    return None, f"salary '{raw}' is not numeric; stored as null"


def clean_optional(raw: str) -> str | None:
    value = raw.strip()
    return value or None
