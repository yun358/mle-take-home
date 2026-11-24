import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

from app.cleaning import (
    MALAYSIA,
    embedding_text,
    normalise_state,
    parse_message,
    parse_updated_at,
)
from app.models import CompanyUpdate, Rejected, RejectReason, StrikeOff

FEED = Path(__file__).parent.parent / "data" / "feed.jsonl"


def upsert(**overrides) -> str:
    """Build a valid upsert message, with some fields replaced."""
    message = {
        "type": "company-upserted",
        "registrationNumber": "SYN-000001",
        "updatedAt": "2026-08-14T09:00:00+08:00",
        "data": {
            "companyName": "Sinar Teguh Bakery Sdn. Bhd.",
            "natureOfBusiness": "Operating cafes and coffee shops",
            "state": "Selangor",
            "industry": "Food & Beverage",
        },
    }
    message.update(overrides)
    return json.dumps(message)


# --- Registration numbers ---


def test_registration_number_is_trimmed_and_uppercased():
    result = parse_message(upsert(registrationNumber=" syn-000949 "))
    assert result.registration_number == "SYN-000949"


def test_missing_registration_number_is_rejected():
    message = json.dumps({"type": "company-upserted", "data": {"companyName": "No Reg Sdn. Bhd."}})
    assert parse_message(message).reason == RejectReason.MISSING_REGISTRATION_NUMBER


def test_integer_registration_number_is_rejected():
    assert parse_message(upsert(registrationNumber=119)).reason == RejectReason.REGISTRATION_NUMBER_NOT_TEXT


# --- Junk messages ---


def test_truncated_json_is_rejected():
    result = parse_message('{"type": "company-upserted", "registrationNumber": "SYN-000509", "data": {"compa')
    assert isinstance(result, Rejected)
    assert result.reason == RejectReason.INVALID_JSON


def test_null_message_is_rejected():
    assert parse_message("null").reason == RejectReason.NOT_AN_OBJECT


def test_data_as_string_is_rejected():
    result = parse_message(upsert(data="companyName=Foo; state=Perak"))
    assert result.reason == RejectReason.DATA_IS_STRING


def test_upsert_without_data_is_rejected():
    assert parse_message(upsert(data=None)).reason == RejectReason.DATA_NULL


def test_strike_off_without_data_is_accepted():
    message = json.dumps(
        {"type": "company-struck-off", "registrationNumber": "SYN-001748", "updatedAt": "2026-08-14T16:00:33+08:00"}
    )
    result = parse_message(message)
    assert isinstance(result, StrikeOff)
    assert result.registration_number == "SYN-001748"


def test_rejected_message_keeps_its_original_body():
    body = "null"
    assert parse_message(body).body == body


# --- Timestamps ---


def test_z_and_plus_eight_are_the_same_moment():
    assert parse_updated_at("2026-08-14T01:03:35Z") == parse_updated_at("2026-08-14T09:03:35+08:00")


def test_timestamp_without_zone_is_malaysian_time():
    assert parse_updated_at("2026-08-14T09:06:19") == datetime(2026, 8, 14, 9, 6, 19, tzinfo=MALAYSIA)


def test_integer_timestamp_is_epoch_milliseconds():
    assert parse_updated_at(1786671038000) == datetime(2026, 8, 14, 9, 30, 38, tzinfo=MALAYSIA)


@pytest.mark.parametrize("value", [None, "", "yesterday", True, 3.5])
def test_missing_or_unparseable_timestamp_is_none(value):
    assert parse_updated_at(value) is None


# --- Field values ---


def test_state_casing_is_normalised():
    assert normalise_state("kuala LUMPUR") == "Kuala Lumpur"


@pytest.mark.parametrize("blank", ["", "   ", None, "Unknown"])
def test_blank_values_become_none(blank):
    data = {"companyName": "Foo Sdn. Bhd.", "natureOfBusiness": blank, "state": blank, "industry": blank}
    result = parse_message(upsert(data=data))
    assert result.nature_of_business is None
    assert result.state is None
    assert result.industry is None


def test_only_the_exact_word_unknown_is_blank():
    result = parse_message(upsert(data={"companyName": "Unknown Hero Trading"}))
    assert result.name == "Unknown Hero Trading"


def test_extra_fields_are_ignored():
    result = parse_message(upsert(source="legacy-crm", ingestedBy="batch-7"))
    assert isinstance(result, CompanyUpdate)


# --- Embedding text ---


def test_embeds_the_description_when_there_is_one():
    assert embedding_text("Foo Sdn. Bhd.", "Operating cafes", "Food & Beverage") == ("Operating cafes", "description")


def test_falls_back_to_name_and_industry():
    assert embedding_text("Foo Sdn. Bhd.", None, "Food & Beverage") == ("Foo Sdn. Bhd.. Food & Beverage", "fallback")


def test_falls_back_to_name_alone():
    assert embedding_text("Foo Sdn. Bhd.", None, None) == ("Foo Sdn. Bhd.", "fallback")


def test_nothing_to_embed():
    assert embedding_text(None, None, None) is None


# --- The real feed ---


def test_real_feed_rejections_match_profiling():
    results = [parse_message(line) for line in FEED.read_text().splitlines()]
    rejected = Counter(r.reason for r in results if isinstance(r, Rejected))
    assert rejected == {
        RejectReason.INVALID_JSON: 5,
        RejectReason.NOT_AN_OBJECT: 6,
        RejectReason.MISSING_REGISTRATION_NUMBER: 7,
        RejectReason.REGISTRATION_NUMBER_NOT_TEXT: 3,
        RejectReason.DATA_IS_STRING: 4,
        RejectReason.DATA_NULL: 5,
    }
    companies = {r.registration_number for r in results if not isinstance(r, Rejected)}
    assert len(companies) == 2000
