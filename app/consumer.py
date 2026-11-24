"""EmbedNStore: read company events from the queue, clean them, embed them, store them, then ack.

Run it with `just consume`. Stop it with Ctrl+C: any message it was holding but hadn't acked goes back to the
queue, so nothing is lost.
"""

import asyncio

import aio_pika
import psycopg

from app import db
from app.cleaning import embedding_text, parse_message
from app.config import DATABASE_URL, QUEUE_NAME, RABBITMQ_URL
from app.embedding import FakeEmbedder
from app.models import Rejected, StrikeOff

PREFETCH_COUNT = 32  # how many unacked messages RabbitMQ hands us at once
RETRY_DELAY_SECONDS = 5  # wait before putting a failed message back, so a database outage isn't a tight loop


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


async def consume() -> None:
    """Read messages from the queue forever, processing and acking them one at a time."""
    connection = db.connect(DATABASE_URL)
    embedder = FakeEmbedder()  # placeholder until the real model is added

    # connect_robust reconnects by itself if RabbitMQ restarts.
    rabbit = await aio_pika.connect_robust(RABBITMQ_URL)
    async with rabbit:
        channel = await rabbit.channel()
        await channel.set_qos(prefetch_count=PREFETCH_COUNT)
        # Exactly how the registry team declares it: durable, no extra arguments. Anything else is refused.
        queue = await channel.declare_queue(QUEUE_NAME, durable=True)
        print(f"waiting for messages on {QUEUE_NAME}", flush=True)

        async with queue.iterator() as messages:
            async for message in messages:
                acked = await handle_message(connection, embedder, message)
                if not acked and connection.broken:  # the database connection was lost: open a new one
                    connection = db.connect(DATABASE_URL)


async def handle_message(
    connection: psycopg.Connection, embedder: FakeEmbedder, message, retry_delay: float = RETRY_DELAY_SECONDS
) -> bool:
    """Process one queue message, then ack it, or put it back on the queue if processing failed.

    Returns True if the message was acked. `message` is an aio_pika message (tests pass a small fake).
    """
    try:
        # This is ordinary (blocking) database code inside async code. That's fine for one consumer
        # handling one message at a time.
        result = process_message(connection, embedder, message.body, message.message_id)
    except Exception as error:
        # Not saved, so don't ack: put it back on the queue to be delivered again.
        print(f"failed {message.message_id}: {error!r}", flush=True)
        await asyncio.sleep(retry_delay)
        await message.nack(requeue=True)
        return False

    await message.ack()  # only now, after process_message has committed
    print(result, message.message_id, flush=True)  # flush: show it now, even in a log file
    return True


def main() -> None:
    try:
        asyncio.run(consume())
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
