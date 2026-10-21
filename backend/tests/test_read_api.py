"""GET endpoints. Scoping comes only from RLS; nothing here filters by region in Python."""
import pytest
from fastapi.testclient import TestClient

from app.importer.pipeline import build_plan, parse_csv
from app.main import create_app

DANA, CALEB, MARISOL = "R-101", "R-102", "R-103"


@pytest.fixture
def client(db, raw_csv):
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/candidates/import",
            files={"file": ("candidates.csv", raw_csv, "text/csv")},
            headers={"X-Recruiter-Id": DANA},
        )
        assert response.status_code == 200
        yield client


@pytest.fixture(scope="module")
def survivors(raw_csv):
    return [model for _, model in build_plan(parse_csv(raw_csv)).survivors]


def get(client, path, recruiter=None, **params):
    headers = {"X-Recruiter-Id": recruiter} if recruiter else {}
    return client.get(path, headers=headers, params=params)


def list_all(client, recruiter, **params):
    response = get(client, "/api/v1/candidates", recruiter, page_size=100, **params)
    assert response.status_code == 200, response.text
    return response.json()


def test_caleb_cannot_fetch_outside_regions(client):
    # C-1007 Grace Lim is PH-MNL; Caleb covers US-MW and US-NE.
    response = get(client, "/api/v1/candidates/C-1007", CALEB)
    assert response.status_code == 404
    assert response.json() == {"detail": "candidate not found"}


def test_admin_can_fetch_any_candidate(client):
    response = get(client, "/api/v1/candidates/C-1007", DANA)
    assert response.status_code == 200
    assert response.json()["first_name"] == "Grace"


def test_marisol_can_fetch_own_region(client):
    response = get(client, "/api/v1/candidates/C-1008", MARISOL)
    assert response.status_code == 200
    assert (response.json()["first_name"], response.json()["last_name"]) == ("Nguyễn", "Thị Hoa")


@pytest.mark.parametrize(
    "recruiter, regions",
    [(CALEB, {"US-MW", "US-NE"}), (MARISOL, {"PH-MNL", "CO-BOG"}), ("R-104", {"US-W", "US-SE"})],
)
def test_list_scoped_to_assigned_regions(client, survivors, recruiter, regions):
    page = list_all(client, recruiter)
    assert {c["region_code"] for c in page["items"]} == regions
    assert page["total"] == sum(1 for m in survivors if m.region_code in regions)


def test_admin_lists_everything(client):
    assert list_all(client, DANA)["total"] == 40


def test_candidate_fields(client):
    [item] = list_all(client, DANA, search="hank.boseman")["items"]
    assert item == {
        "candidate_id": "C-1038",
        "first_name": "Hank",
        "last_name": "Boseman",
        "email": "hank.boseman@gmail.com",
        "region_code": "US-MW",
        "desired_role": "DevOps Engineer",
        "status": "active",
        "applied_date": "2026-06-30",
    }


def test_unknown_recruiter_403(client):
    response = get(client, "/api/v1/candidates", "R-999")
    assert response.status_code == 403
    assert get(client, "/api/v1/candidates/C-1007", "R-999").status_code == 403


def test_missing_header_403(client):
    assert get(client, "/api/v1/candidates").status_code == 403


@pytest.mark.parametrize(
    "term, expected",
    [
        ("nguy", {"C-1008"}),
        ("cárdenas", {"C-1010"}),
        ("CÁRDENAS", {"C-1010"}),
        ("müller", {"C-1015"}),
        ("Tomás Herrera", {"C-1006"}),
        ("recruiter ops", {"C-1018"}),
    ],
)
def test_search_unicode_and_case_insensitive(client, term, expected):
    assert {c["candidate_id"] for c in list_all(client, DANA, search=term)["items"]} == expected


def test_search_is_still_scoped(client):
    # Jürgen Müller is US-NE: Caleb sees him, Marisol does not.
    assert list_all(client, CALEB, search="müller")["total"] == 1
    assert list_all(client, MARISOL, search="müller")["total"] == 0


@pytest.mark.parametrize("term", ["%", "_", "\\", "' OR '1'='1"])
def test_search_wildcards_and_quotes_are_literal(client, term):
    assert list_all(client, DANA, search=term)["total"] == 0


def test_status_filter(client):
    assert [c["candidate_id"] for c in list_all(client, DANA, status="on_hold")["items"]] == ["C-1048"]
    assert get(client, "/api/v1/candidates", DANA, status="bogus").status_code == 422


def test_pagination(client):
    pages = [get(client, "/api/v1/candidates", DANA, page=n, page_size=15).json() for n in (1, 2, 3, 4)]
    assert [len(p["items"]) for p in pages] == [15, 15, 10, 0]
    assert {p["total"] for p in pages} == {40}
    ids = [c["candidate_id"] for p in pages for c in p["items"]]
    assert len(set(ids)) == 40
    assert get(client, "/api/v1/candidates", DANA, page_size=101).status_code == 422
    assert get(client, "/api/v1/candidates", DANA, page=0).status_code == 422


def test_default_order_newest_first(client):
    items = list_all(client, DANA)["items"]
    keys = [(c["applied_date"], c["candidate_id"]) for c in items]
    assert keys == sorted(keys, key=lambda k: (-int(k[0].replace("-", "")), k[1]))


def test_dana_then_caleb_same_client(client):
    assert list_all(client, DANA)["total"] == 40
    caleb = list_all(client, CALEB)
    assert {c["region_code"] for c in caleb["items"]} == {"US-MW", "US-NE"}


def test_recruiters_list(client):
    response = client.get("/api/v1/recruiters")
    assert response.status_code == 200
    recruiters = response.json()
    assert [r["recruiter_id"] for r in recruiters] == ["R-101", "R-102", "R-103", "R-104", "R-105"]
    assert recruiters[0] == {"recruiter_id": "R-101", "full_name": "Dana Whitmore", "is_admin": True, "regions": []}
    assert recruiters[2]["regions"] == ["CO-BOG", "PH-MNL"]
