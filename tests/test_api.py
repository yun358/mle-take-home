"""The API, called as a plain Python function against the companies_test database (with the fake embedder).

FastAPI turns each request into a call of `similar_companies(...)`, so calling it directly tests the same
logic without starting a server. One thing FastAPI normally does for us is fill in the default `limit`, so
these tests always pass `limit` themselves.
"""

import json

import pytest
from fastapi.responses import JSONResponse

from app import api, db
from app.consumer import process_message
from tests.helpers import load_feed

CAFES = "Operating cafes and coffee shops"
GLOVES = "Production of rubber gloves for export"
SEED = "test-seed"


@pytest.fixture(autouse=True)  # autouse: every test in this file gets it without asking
def api_uses_test_database(monkeypatch, test_database_url):
    # monkeypatch swaps a value for the duration of one test, then puts the original back.
    monkeypatch.setattr(api, "DATABASE_URL", test_database_url)


def add_company(connection, embedder, number: str, description: str, struck_off: bool = False) -> None:
    upsert = {
        "type": "company-upserted",
        "registrationNumber": number,
        "updatedAt": "2026-08-14T09:00:00+08:00",
        "data": {"companyName": f"Company {number}", "natureOfBusiness": description, "industry": "Food & Beverage"},
    }
    process_message(connection, embedder, json.dumps(upsert))
    if struck_off:
        strike_off = {"type": "company-struck-off", "registrationNumber": number, "updatedAt": "2026-08-15T09:00:00Z"}
        process_message(connection, embedder, json.dumps(strike_off))


def call(registration_number: str, limit: int = 4) -> tuple[int, dict]:
    """Call the endpoint function and return (HTTP status, JSON body), whether it succeeded or not."""
    response = api.similar_companies(registration_number, limit=limit)
    if isinstance(response, JSONResponse):  # errors come back as a JSONResponse with their status code
        return response.status_code, json.loads(response.body)
    return 200, response


def numbers(body: dict) -> list[str]:
    """The registration numbers in a response, in order."""
    return [card["registrationNumber"] for card in body["similar"]]


# --- Results ---


def test_most_similar_comes_first(connection, embedder):
    add_company(connection, embedder, "SYN-000001", CAFES)
    add_company(connection, embedder, "SYN-000002", GLOVES)
    add_company(connection, embedder, "SYN-000003", CAFES)  # same description as SYN-000001: distance 0

    status, body = call("SYN-000001", limit=2)

    assert status == 200
    assert numbers(body) == ["SYN-000003", "SYN-000002"]


def test_never_includes_itself_or_struck_off_companies(connection, embedder):
    add_company(connection, embedder, "SYN-000001", CAFES)
    add_company(connection, embedder, "SYN-000002", CAFES)
    add_company(connection, embedder, "SYN-000003", CAFES, struck_off=True)

    status, body = call("SYN-000001", limit=20)

    assert numbers(body) == ["SYN-000002"]


def test_each_card_has_what_the_portal_draws(connection, embedder):
    add_company(connection, embedder, "SYN-000001", CAFES)
    add_company(connection, embedder, "SYN-000002", CAFES)

    status, body = call("SYN-000001")

    assert body["similar"] == [
        {"registrationNumber": "SYN-000002", "name": "Company SYN-000002", "industry": "Food & Beverage", "state": None}
    ]


def test_struck_off_company_page_still_works(connection, embedder):
    add_company(connection, embedder, "SYN-000001", CAFES)
    add_company(connection, embedder, "SYN-000002", CAFES, struck_off=True)

    status, body = call("SYN-000002")

    assert status == 200
    assert body["status"] == "struck_off"
    assert numbers(body) == ["SYN-000001"]


def test_company_without_embedding_gets_an_empty_list(connection, embedder):
    # A strike-off for a company we've never seen leaves a placeholder row with no details or embedding.
    strike_off = {"type": "company-struck-off", "registrationNumber": "SYN-000001", "updatedAt": "2026-08-15T09:00:00Z"}
    process_message(connection, embedder, json.dumps(strike_off))

    status, body = call("SYN-000001")

    assert status == 200
    assert body["similar"] == []


def test_tied_companies_reshuffle_with_a_new_seed_but_most_similar_stay_first(connection, embedder):
    for i in range(1, 12):  # 11 companies with the same description: 10 exact ties for SYN-000001
        add_company(connection, embedder, f"SYN-{i:06d}", CAFES)
    add_company(connection, embedder, "SYN-000099", GLOVES)  # different description: farther than every tie

    def top(seed: str, limit: int = 4) -> list[str]:
        return [row["registration_number"] for row in db.find_similar(connection, "SYN-000001", limit, seed)]

    assert top("a") == top("a")  # same seed, same order (so the query is testable)
    assert top("a") != top("b")  # new seed, other tied companies
    assert top("a", limit=11)[-1] == "SYN-000099"  # shuffling never lets a less similar company jump ahead


# --- Errors ---


def test_unknown_company_is_404(connection):
    assert call("SYN-999999") == (404, {"error": "company_not_found"})


def test_invalid_registration_number_is_400(connection):
    assert call("hello") == (400, {"error": "invalid_registration_number"})


def test_registration_number_is_normalised(connection, embedder):
    add_company(connection, embedder, "SYN-000001", CAFES)

    status, body = call(" syn-000001 ")

    assert status == 200
    assert body["registrationNumber"] == "SYN-000001"


def test_database_down_is_503(monkeypatch):
    monkeypatch.setattr(api, "DATABASE_URL", "postgresql://postgres:postgres@localhost:5999/companies")  # nothing there

    assert call("SYN-000001") == (503, {"error": "service_unavailable"})
    assert api.health().status_code == 503


# --- The whole feed ---


def test_every_active_company_gets_a_full_panel(connection, embedder):
    # The portal draws four cards. Every active company must get four, each with a name.
    load_feed(connection, embedder)
    active = connection.execute("SELECT registration_number FROM companies WHERE NOT struck_off").fetchall()

    short_panels = []
    for (number,) in active:
        similar = db.find_similar(connection, number, 4, SEED)
        if len(similar) != 4 or any(row["name"] is None for row in similar):
            short_panels.append(number)

    assert len(active) == 1992
    assert short_panels == []
