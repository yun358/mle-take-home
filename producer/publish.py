"""Replays the registry feed (data/feed.jsonl) onto the `company-events` queue, one message per line, as received upstream."""

import argparse
import asyncio
import hashlib
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import aio_pika

QUEUE: Final = "company-events"


async def publish(lines: Sequence[str], url: str) -> int:
    """Publish each line as one message, in order. Returns how many were published."""
    connection = await aio_pika.connect_robust(url)
    async with connection:
        channel = await connection.channel(publisher_confirms=True)
        # The registry team owns this queue: durable, no extra arguments.
        await channel.declare_queue(QUEUE, durable=True)
        for line in lines:
            message = aio_pika.Message(
                line.encode(),
                message_id=hashlib.sha256(line.encode()).hexdigest(),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            )
            await channel.default_exchange.publish(message, routing_key=QUEUE)
    return len(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path("data/feed.jsonl"))
    port = os.environ.get("RABBITMQ_PORT", "5672")
    parser.add_argument("--url", default=os.environ.get("RABBITMQ_URL", f"amqp://guest:guest@localhost:{port}/"))
    args = parser.parse_args()
    feed: Path = args.file
    url: str = args.url
    count = asyncio.run(publish(feed.read_text(encoding="utf-8").splitlines(), url))
    print(f"published {count} messages to {QUEUE}")


if __name__ == "__main__":
    main()
