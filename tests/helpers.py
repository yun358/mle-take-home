"""Small functions shared by several test files."""

import hashlib
from pathlib import Path

from app.consumer import process_message

FEED = Path(__file__).parent.parent / "data" / "feed.jsonl"


def load_feed(connection, embedder) -> None:
    """Process every line of the feed, with the same message_id the producer gives it."""
    for line in FEED.read_text(encoding="utf-8").splitlines():
        message_id = hashlib.sha256(line.encode()).hexdigest()
        process_message(connection, embedder, line, message_id)


def count(connection, sql: str) -> int:
    """Run a SELECT count(*) query and return the number."""
    return connection.execute(sql).fetchone()[0]
