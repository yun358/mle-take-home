"""EmbedNStore: read company events from the queue, clean them, embed them, store them, then ack."""

import psycopg

from app import db
from app.cleaning import embedding_text, parse_message
from app.embedding import Embedder
from app.models import CompanyUpdate, Rejected, StrikeOff


def process_message(
    connection: psycopg.Connection, embedder: Embedder, body: bytes | str, message_id: str | None = None
) -> str:
    """Clean and store one message in a single transaction. Returns what happened, for logging.

    If anything fails, the transaction rolls back and the exception propagates, so the caller doesn't ack
    and the message is redelivered.
    """
    message = parse_message(body)

    with connection.transaction():
        if isinstance(message, Rejected):
            db.save_rejected(connection, message, message_id)
            return f"rejected:{message.reason}"

        if isinstance(message, StrikeOff):
            changed = db.strike_off_company(connection, message)
            return "struck_off" if changed else "skipped_older"

        assert isinstance(message, CompanyUpdate)
        if not db.upsert_company(connection, message):
            return "skipped_older"

        reembedded = refresh_embedding(connection, embedder, message.registration_number)
        return "updated_and_embedded" if reembedded else "updated"


def refresh_embedding(connection: psycopg.Connection, embedder: Embedder, registration_number: str) -> bool:
    """Re-embed only if the text to embed (or the model) changed: embedding is the expensive step."""
    company = db.get_company(connection, registration_number)
    choice = embedding_text(company.name, company.nature_of_business, company.industry)
    if choice is None:
        return False

    text, source = choice
    if text == company.embedded_text and company.embedding_model == embedder.model_name:
        return False

    [vector] = embedder.embed([text])
    db.save_embedding(connection, registration_number, text, source, embedder.model_name, vector)
    return True
