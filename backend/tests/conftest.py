from pathlib import Path

import pytest

CANDIDATES_CSV = Path("/data/candidates_import.csv")


@pytest.fixture(scope="session")
def raw_csv() -> bytes:
    return CANDIDATES_CSV.read_bytes()
