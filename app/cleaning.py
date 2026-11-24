"""Turn a raw queue message into a clean record or a rejection.

Everything here is a pure function: no database, no queue, no model. That makes each rule easy to test.
"""

import json
from datetime import UTC, datetime, timedelta, timezone

from app.models import (
    DATA_IS_STRING,
    DATA_NULL,
    INVALID_JSON,
    MISSING_REGISTRATION_NUMBER,
    NOT_AN_OBJECT,
    REGISTRATION_NUMBER_NOT_TEXT,
    UNKNOWN_EVENT_TYPE,
    CompanyUpdate,
    Rejected,
    StrikeOff,
)

MALAYSIA = timezone(timedelta(hours=8))

UPSERT = "company-upserted"
STRUCK_OFF = "company-struck-off"

# Values that mean "we don't know". A blank value never overwrites a stored one.
BLANK_VALUES = {"", "Unknown"}


def clean_text(value: object) -> str | None:
    """Return the trimmed string, or None if the value is blank or not text."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value in BLANK_VALUES:
        return None
    return value


def normalise_registration_number(value: str) -> str:
    """' syn-000949 ' -> 'SYN-000949'."""
    return value.strip().upper()


def normalise_state(value: object) -> str | None:
    """'kuala LUMPUR' -> 'Kuala Lumpur'."""
    text = clean_text(value)
    return text.title() if text else None


def parse_updated_at(value: object) -> datetime | None:
    """Parse the feed's timestamp formats into a timezone-aware datetime.

    - ISO with an offset or 'Z': used as given.
    - ISO with no timezone: assumed to be Malaysian time (+08:00), like almost every other timestamp.
    - Integer: epoch milliseconds.
    - Missing or unparseable: None, which the database treats as older than everything.
    """
    if isinstance(value, bool):  # bool is a subclass of int in Python; it isn't a timestamp
        return None
    if isinstance(value, int):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=MALAYSIA)
        return parsed
    return None


def parse_message(body: bytes | str) -> CompanyUpdate | StrikeOff | Rejected:
    """Clean one message from the queue."""
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body

    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        return Rejected(INVALID_JSON, text)

    if not isinstance(message, dict):
        return Rejected(NOT_AN_OBJECT, text)

    raw_registration_number = message.get("registrationNumber")
    if raw_registration_number is None:
        return Rejected(MISSING_REGISTRATION_NUMBER, text)
    if not isinstance(raw_registration_number, str):
        return Rejected(REGISTRATION_NUMBER_NOT_TEXT, text)
    registration_number = normalise_registration_number(raw_registration_number)
    if not registration_number:
        return Rejected(MISSING_REGISTRATION_NUMBER, text)

    updated_at = parse_updated_at(message.get("updatedAt"))
    event_type = message.get("type")

    if event_type == STRUCK_OFF:
        return StrikeOff(registration_number, updated_at)

    if event_type != UPSERT:
        return Rejected(UNKNOWN_EVENT_TYPE, text)

    data = message.get("data")
    if isinstance(data, str):
        return Rejected(DATA_IS_STRING, text)
    if not isinstance(data, dict):
        return Rejected(DATA_NULL, text)

    return CompanyUpdate(
        registration_number=registration_number,
        updated_at=updated_at,
        name=clean_text(data.get("companyName")),
        nature_of_business=clean_text(data.get("natureOfBusiness")),
        state=normalise_state(data.get("state")),
        industry=clean_text(data.get("industry")),
    )


def embedding_text(name: str | None, nature_of_business: str | None, industry: str | None) -> tuple[str, str] | None:
    """Choose the text to embed, and say where it came from.

    The description is what we match on. Without one, name + industry is the most relevant text left,
    so the company still gets recommended instead of being lost. State is never used: it's a location,
    not a business.
    """
    if nature_of_business:
        return nature_of_business, "description"
    if name and industry:
        return f"{name}. {industry}", "fallback"
    if name:
        return name, "fallback"
    return None
