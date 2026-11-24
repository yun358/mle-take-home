"""The consumer: acking, failures, and loading the whole feed.

No RabbitMQ here. Loop tests hand handle_message a small fake queue message; feed tests send each line
straight through process_message, which is what handle_message calls for every message.
"""

import asyncio
import json

import psycopg
import pytest

from app import db
from app.consumer import handle_message, process_message
from tests.helpers import count, load_feed

# A valid upsert, used by several tests.
GOOD_MESSAGE = json.dumps(
    {
        "type": "company-upserted",
        "registrationNumber": "SYN-000675",
        "updatedAt": "2026-08-14T09:00:00+08:00",
        "data": {"companyName": "Pantas Logistik Sdn. Bhd.", "natureOfBusiness": "Cold chain transport"},
    }
)


class FakeQueueMessage:
    """Stands in for an aio_pika message: it has a body and an id, and records whether it was acked or nacked."""

    def __init__(self, body: str, message_id: str = "test-id"):
        self.body = body.encode()  # RabbitMQ delivers bytes
        self.message_id = message_id
        self.acked = False
        self.nacked = False
        self.requeued = False

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, requeue: bool) -> None:
        self.nacked = True
        self.requeued = requeue


class BrokenEmbedder:
    """An embedder that always fails, to check what happens when something breaks partway through."""

    model_name = "broken"

    def embed(self, texts: list[str]) -> list:
        raise RuntimeError("model crashed")


def all_companies(connection) -> list[tuple]:
    """Every stored company, sorted, so two snapshots can be compared with ==."""
    return connection.execute(
        """
        SELECT registration_number, name, nature_of_business, state, industry, updated_at, struck_off,
               embedded_text, embedding_model
        FROM companies ORDER BY registration_number
        """
    ).fetchall()


# --- Failures ---


def test_failure_saves_nothing_and_raises(connection):
    # The upsert succeeds, then embedding fails. The upsert must be rolled back too, and the error must
    # reach the caller, so the consumer loop knows not to ack and RabbitMQ delivers the message again.
    with pytest.raises(RuntimeError):  # the test passes only if process_message raises RuntimeError
        process_message(connection, BrokenEmbedder(), GOOD_MESSAGE)

    assert db.get_company(connection, "SYN-000675") is None


# --- Acking (handle_message is async, so asyncio.run calls it from these ordinary tests) ---


def test_good_message_is_saved_then_acked(connection, embedder, test_database_url):
    message = FakeQueueMessage(GOOD_MESSAGE)

    asyncio.run(handle_message(connection, embedder, message))

    assert message.acked and not message.nacked
    # A second, separate connection only sees committed data, so this shows the save was committed.
    with psycopg.connect(test_database_url) as other:
        assert other.execute("SELECT count(*) FROM companies").fetchone()[0] == 1


def test_bad_message_is_stored_and_acked(connection, embedder):
    # Acked, so a bad message never blocks the queue.
    message = FakeQueueMessage("null")

    asyncio.run(handle_message(connection, embedder, message))

    assert message.acked
    assert count(connection, "SELECT count(*) FROM rejected_messages") == 1


def test_failed_message_is_put_back_not_acked(connection):
    message = FakeQueueMessage(GOOD_MESSAGE)

    asyncio.run(handle_message(connection, BrokenEmbedder(), message, retry_delay=0))

    assert message.nacked and message.requeued  # back on the queue, to be delivered again
    assert not message.acked
    assert db.get_company(connection, "SYN-000675") is None


# --- The whole feed ---


def test_whole_feed_loads_with_expected_counts(connection, embedder):
    load_feed(connection, embedder)

    assert count(connection, "SELECT count(*) FROM companies") == 2000
    assert count(connection, "SELECT count(*) FROM companies WHERE struck_off") == 8
    assert count(connection, "SELECT count(*) FROM companies WHERE embedding IS NULL") == 0
    # 30 lines are rejected (see test_cleaning), but the 6 `null` lines are identical, so they share one
    # message_id and are stored once, like a redelivery: 30 - 6 + 1 = 25 rows.
    assert count(connection, "SELECT count(*) FROM rejected_messages") == 25


def test_loading_the_feed_twice_changes_no_company(connection, embedder):
    # At-least-once delivery: the whole feed arriving again must leave every company exactly as it was.
    load_feed(connection, embedder)
    before = all_companies(connection)

    load_feed(connection, embedder)

    assert all_companies(connection) == before


def test_loading_the_feed_twice_stores_each_rejection_once(connection, embedder):
    load_feed(connection, embedder)
    load_feed(connection, embedder)

    assert count(connection, "SELECT count(*) FROM rejected_messages") == 25  # same as after one load
