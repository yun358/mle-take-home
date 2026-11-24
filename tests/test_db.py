"""Storage rules against a real Postgres (the separate companies_test database), with the fake embedder."""

import json

from app import db
from app.consumer import process_message
from app.embedding import FakeEmbedder


def upsert_message(updated_at: str | None, data_changes: dict | None = None) -> str:
    """An upsert for SYN-000675 as JSON text. `data_changes` replaces fields inside `data`."""
    fields = {
        "companyName": "Pantas Logistik Sdn. Bhd.",
        "natureOfBusiness": "Cold chain transport and storage of frozen goods",
        "state": "Selangor",
        "industry": "Logistics",
    }
    if data_changes:
        fields.update(data_changes)
    message = {"type": "company-upserted", "registrationNumber": "SYN-000675", "data": fields}
    if updated_at is not None:
        message["updatedAt"] = updated_at
    return json.dumps(message)


def strike_off_message(updated_at: str) -> str:
    """A strike-off for SYN-000675 as JSON text."""
    return json.dumps({"type": "company-struck-off", "registrationNumber": "SYN-000675", "updatedAt": updated_at})


T1 = "2026-08-14T09:00:00+08:00"
T2 = "2026-08-14T10:00:00+08:00"
T3 = "2026-08-14T11:00:00+08:00"


# --- Newer wins ---


def test_older_update_after_newer_one_is_ignored(connection, embedder):
    process_message(connection, embedder, upsert_message(T2, {"natureOfBusiness": "Cold chain transport"}))
    result = process_message(connection, embedder, upsert_message(T1, {"natureOfBusiness": "General trading"}))

    assert result == "skipped_older"
    assert db.get_company(connection, "SYN-000675")["nature_of_business"] == "Cold chain transport"


def test_same_message_twice_changes_nothing(connection, embedder):
    process_message(connection, embedder, upsert_message(T1))
    assert process_message(connection, embedder, upsert_message(T1)) == "skipped_older"
    assert connection.execute("SELECT count(*) FROM companies").fetchone()[0] == 1


def test_newer_message_with_same_data_advances_time_without_reembedding(connection, embedder):
    assert process_message(connection, embedder, upsert_message(T1)) == "updated_and_embedded"
    assert process_message(connection, embedder, upsert_message(T2)) == "updated"

    company = db.get_company(connection, "SYN-000675")
    assert company["updated_at"].isoformat() == "2026-08-14T02:00:00+00:00"


def test_out_of_order_versions_end_on_the_newest(connection, embedder):
    # Arrival order is T1, T3, T2. The newest version (T3, Catering) must win, not the last to arrive.
    process_message(connection, embedder, upsert_message(T1, {"natureOfBusiness": "Bakery"}))
    process_message(connection, embedder, upsert_message(T3, {"natureOfBusiness": "Catering"}))
    process_message(connection, embedder, upsert_message(T2, {"natureOfBusiness": "Bakery"}))

    assert db.get_company(connection, "SYN-000675")["nature_of_business"] == "Catering"


def test_timestamps_in_different_zones_compare_as_moments(connection, embedder):
    process_message(connection, embedder, upsert_message("2026-08-14T09:30:00+08:00", {"natureOfBusiness": "Newer"}))
    # 01:00Z is 09:00+08:00, so it's older than 09:30+08:00 and must not win.
    process_message(connection, embedder, upsert_message("2026-08-14T01:00:00Z", {"natureOfBusiness": "Older"}))

    assert db.get_company(connection, "SYN-000675")["nature_of_business"] == "Newer"


# --- Partial updates ---


def test_blank_field_keeps_the_stored_value(connection, embedder):
    process_message(connection, embedder, upsert_message(T1, {"state": "Selangor"}))
    process_message(connection, embedder, upsert_message(T2, {"state": ""}))

    assert db.get_company(connection, "SYN-000675")["state"] == "Selangor"


def test_new_description_is_reembedded(connection, embedder):
    process_message(connection, embedder, upsert_message(T1))
    result = process_message(connection, embedder, upsert_message(T2, {"natureOfBusiness": "Frozen food wholesale"}))

    assert result == "updated_and_embedded"
    assert db.get_company(connection, "SYN-000675")["embedded_text"] == "Frozen food wholesale"


def test_new_state_only_is_not_reembedded(connection, embedder):
    process_message(connection, embedder, upsert_message(T1))
    assert process_message(connection, embedder, upsert_message(T2, {"state": "Johor"})) == "updated"


def test_company_without_description_gets_fallback_embedding(connection, embedder):
    process_message(connection, embedder, upsert_message(T1, {"natureOfBusiness": None}))

    company = db.get_company(connection, "SYN-000675")
    assert company["embedded_text"] == "Pantas Logistik Sdn. Bhd.. Logistics"


def test_new_model_reembeds_unchanged_text(connection, embedder):
    process_message(connection, embedder, upsert_message(T1))

    new_model = FakeEmbedder()
    new_model.model_name = "fake-hash-v2"  # same text, different model
    assert process_message(connection, new_model, upsert_message(T2)) == "updated_and_embedded"
    assert db.get_company(connection, "SYN-000675")["embedding_model"] == "fake-hash-v2"


# --- Missing timestamps ---


def test_new_company_without_timestamp_is_inserted(connection, embedder):
    process_message(connection, embedder, upsert_message(None))
    assert db.get_company(connection, "SYN-000675") is not None


def test_message_without_timestamp_never_overwrites(connection, embedder):
    process_message(connection, embedder, upsert_message(T1))
    result = process_message(
        connection, embedder, upsert_message(None, {"companyName": "Unknown", "natureOfBusiness": "Other"})
    )

    assert result == "skipped_older"
    assert db.get_company(connection, "SYN-000675")["name"] == "Pantas Logistik Sdn. Bhd."


# --- Struck off ---


def test_strike_off_flags_company_and_keeps_details(connection, embedder):
    process_message(connection, embedder, upsert_message(T1))
    process_message(connection, embedder, strike_off_message(T2))

    company = db.get_company(connection, "SYN-000675")
    assert company["struck_off"]
    assert company["name"] == "Pantas Logistik Sdn. Bhd."


def test_strike_off_before_any_upsert_creates_tombstone(connection, embedder):
    process_message(connection, embedder, strike_off_message(T2))

    company = db.get_company(connection, "SYN-000675")
    assert company["struck_off"]
    assert company["name"] is None


def test_older_upsert_after_strike_off_stays_struck_off(connection, embedder):
    process_message(connection, embedder, strike_off_message(T2))
    process_message(connection, embedder, upsert_message(T1))

    assert db.get_company(connection, "SYN-000675")["struck_off"]


def test_newer_upsert_after_strike_off_reactivates(connection, embedder):
    process_message(connection, embedder, upsert_message(T1))
    process_message(connection, embedder, strike_off_message(T2))
    process_message(connection, embedder, upsert_message(T3))

    assert not db.get_company(connection, "SYN-000675")["struck_off"]


# --- Rejections ---


def test_bad_message_is_stored_with_reason(connection, embedder):
    assert process_message(connection, embedder, "null", message_id="abc") == "rejected:not_an_object"

    row = connection.execute("SELECT message_id, reason, body FROM rejected_messages").fetchone()
    assert row == ("abc", "not_an_object", "null")
