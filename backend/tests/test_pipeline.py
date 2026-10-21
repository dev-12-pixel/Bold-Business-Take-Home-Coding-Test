"""Parse -> validate -> dedup against the real file (CLAUDE.md section 3) plus edge cases."""
from datetime import date

import pytest

from app.importer.pipeline import EXPECTED_HEADER, FileError, build_plan, parse_csv

HEADER = ",".join(EXPECTED_HEADER)
VALID = "C-9001,Ana,Lopez,ana@example.com,,US-W,QA Engineer,50000,2026-07-01,Active,Indeed,"


def plan_for(*lines: str):
    return build_plan(parse_csv("\r\n".join([HEADER, *lines]).encode()))


@pytest.fixture(scope="module")
def plan(raw_csv):
    return build_plan(parse_csv(raw_csv))


def survivor(plan, email):
    [(row, model)] = [(r, m) for r, m in plan.survivors if m.email == email]
    return row, model


def reason(plan, row):
    [rejection] = [r for r in plan.rejected if r.row == row]
    return rejection.reason


def test_parse_counts_records_not_lines(raw_csv):
    rows = parse_csv(raw_csv)
    assert len(rows) == 53
    assert rows[0].row == 2
    assert rows[-1].row == 54


def test_full_file_plan(plan):
    assert len(plan.survivors) == 40
    assert sorted(r.row for r in plan.rejected) == [35, 36, 37, 38, 42, 43, 47, 49, 53, 54]
    assert {(m.row, m.candidate_id, m.kept_row) for m in plan.merges} == {
        (2, "C-1001", 33),
        (5, "C-1004", 32),
        (17, "C-1016", 34),
    }
    assert plan.warnings == []


def test_rejection_reasons(plan):
    assert reason(plan, 35) == "email: invalid address 'marcus.reed[at]gmail.com'"
    assert reason(plan, 36) == "email: invalid address 'tina.holloway.gmail.com'"
    assert reason(plan, 37) == "email: required"
    assert reason(plan, 38).startswith("last_name: contains characters")
    assert reason(plan, 42) == "applied_date: not a valid date '2026-02-30'"
    assert reason(plan, 43) == "applied_date: required"
    assert reason(plan, 47) == "region_code: unknown region 'ZZ-99'"
    assert reason(plan, 49) == "status: unknown status 'actve'"
    assert reason(plan, 53) == "candidate_id: C-1010 already used by row 11 with a different email"
    assert reason(plan, 54) == "region_code: required"
    assert {r.row: r.candidate_id for r in plan.rejected}[53] == "C-1010"


def test_last_occurrence_wins(plan):
    row, amara = survivor(plan, "amara.diallo@gmail.com")
    assert row == 34
    assert (amara.candidate_id, amara.first_name) == ("C-1032", "A.")
    assert amara.salary_expectation == 110000
    assert amara.applied_date == date(2026, 6, 20)

    row, alicia = survivor(plan, "alicia.trent@gmail.com")
    assert (row, alicia.candidate_id, alicia.source) == (33, "C-1031", "Indeed")


def test_normalized_survivor_values(plan):
    by_row = {row: m for row, m in plan.survivors}
    assert (by_row[48].status, by_row[48].salary_expectation) == ("active", 85000)
    assert by_row[46].region_code == "US-W"
    assert by_row[44].region_code == "US-MW"
    assert by_row[45].region_code == "CO-BOG"
    assert (by_row[50].status, by_row[50].salary_expectation) == ("on_hold", None)
    assert by_row[40].applied_date == date(2026, 6, 30)
    assert by_row[41].applied_date == date(2026, 5, 14)
    assert by_row[52].notes == "Interview notes:\nRound 1 passed.\nRound 2 pending scheduling."
    assert (by_row[9].first_name, by_row[9].last_name) == ("Nguyễn", "Thị Hoa")
    assert by_row[39].notes == "' OR '1'='1"
    assert by_row[11].first_name == "Sofía"  # C-1010 keeps its first holder


def test_all_field_errors_reported_in_column_order():
    plan = plan_for("C-9002,Ana,Lopez,not-an-email,,ZZ-99,QA,1,2026-07-01,Active,Indeed,")
    assert plan.rejected[0].reason == (
        "email: invalid address 'not-an-email'; region_code: unknown region 'ZZ-99'"
    )


def test_salary_warning_on_survivor():
    plan = plan_for(VALID.replace("50000", "negotiable"))
    assert plan.survivors[0][1].salary_expectation is None
    assert [(w.row, w.candidate_id, w.message) for w in plan.warnings] == [
        (2, "C-9001", "salary 'negotiable' is not numeric; stored as null")
    ]


def test_superseded_row_warning_dropped():
    plan = plan_for(VALID.replace("50000", "negotiable"), VALID)
    assert plan.warnings == []
    assert [(m.row, m.kept_row) for m in plan.merges] == [(2, 3)]


def test_invalid_later_duplicate_does_not_supersede():
    plan = plan_for(VALID, VALID.replace("US-W", "ZZ-99"))
    assert [row for row, _ in plan.survivors] == [2]
    assert [r.row for r in plan.rejected] == [3]


def test_wrong_field_count_rejected():
    plan = plan_for("C-9003,Ana,Lopez")
    assert plan.rejected[0].reason == "expected 12 fields, got 3"
    assert plan.rejected[0].candidate_id == "C-9003"


def test_blank_lines_ignored():
    assert len(parse_csv(f"{HEADER}\r\n\r\n{VALID}\r\n".encode())) == 1


def test_bom_accepted():
    assert len(parse_csv(f"﻿{HEADER}\n{VALID}\n".encode())) == 1


def test_bad_header_raises():
    with pytest.raises(FileError, match="^unexpected header"):
        parse_csv(b"id,name\nC-1,x\n")


def test_non_utf8_raises():
    with pytest.raises(FileError, match="^file is not valid UTF-8$"):
        parse_csv(HEADER.encode() + b"\n\xff\xfe\n")


def test_empty_file_raises():
    with pytest.raises(FileError, match="^file is empty$"):
        parse_csv(b"")
