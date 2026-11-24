"""The shapes a message can take after cleaning."""

from dataclasses import dataclass
from datetime import datetime

# Why a message was rejected. Stored as text in the rejected_messages table.
INVALID_JSON = "invalid_json"
NOT_AN_OBJECT = "not_an_object"
MISSING_REGISTRATION_NUMBER = "missing_registration_number"
REGISTRATION_NUMBER_NOT_TEXT = "registration_number_not_text"
UNKNOWN_EVENT_TYPE = "unknown_event_type"
DATA_IS_STRING = "data_is_string"
DATA_NULL = "data_null"


@dataclass
class CompanyUpdate:
    """A `company-upserted` event. Any field except the registration number may be None (blank)."""

    registration_number: str
    updated_at: datetime | None  # None = missing, treated as older than everything
    name: str | None
    nature_of_business: str | None
    state: str | None
    industry: str | None


@dataclass
class StrikeOff:
    """A `company-struck-off` event."""

    registration_number: str
    updated_at: datetime | None


@dataclass
class Rejected:
    """A message we can't use. It's stored with its reason, then acked."""

    reason: str  # one of the reasons at the top of this file
    body: str
