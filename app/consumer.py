"""EmbedNStore: read company events from the queue, clean them, embed them, store them, then ack."""

import psycopg

from app import db
from app.cleaning import embedding_text, parse_message
from app.embedding import FakeEmbedder
from app.models import Rejected, StrikeOff


def process_message(
    connection: psycopg.Connection, embedder: FakeEmbedder, body: bytes | str, message_id: str | None = None
) -> str:
    """Clean and store one message, then commit. Returns what happened, for logging.

    All the writes for one message are committed together. If anything fails, they're all rolled back and
    the error is raised again, so the caller doesn't ack and RabbitMQ delivers the message again.
    """
    message = parse_message(body)

    try:
        if isinstance(message, Rejected):
            db.save_rejected(connection, message, message_id)
            result = f"rejected:{message.reason}"
        elif isinstance(message, StrikeOff):
            changed = db.strike_off_company(connection, message)
            result = "struck_off" if changed else "skipped_older"
        else:  # a CompanyUpdate
            changed = db.upsert_company(connection, message)
            if not changed:
                result = "skipped_older"
            elif refresh_embedding(connection, embedder, message.registration_number):
                result = "updated_and_embedded"
            else:
                result = "updated"
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    return result


def refresh_embedding(connection: psycopg.Connection, embedder: FakeEmbedder, registration_number: str) -> bool:
    """Re-embed only if the text to embed (or the model) changed: embedding is the expensive step."""
    # Read the row back instead of using the message: after the upsert, the row holds the merged data
    # (blank fields in the message kept their stored values), and that's what we want to embed.
    # The row always exists here, because the upsert just wrote it.
    company = db.get_company(connection, registration_number)
    choice = embedding_text(company["name"], company["nature_of_business"], company["industry"])
    if choice is None:
        return False

    text, source = choice
    if text == company["embedded_text"] and company["embedding_model"] == embedder.model_name:
        return False

    vector = embedder.embed([text])[0]
    db.save_embedding(connection, registration_number, text, source, embedder.model_name, vector)
    return True
