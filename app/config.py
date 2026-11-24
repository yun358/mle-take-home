"""Settings, read from environment variables.

The defaults match the template's docker-compose.yml, including its POSTGRES_PORT / RABBITMQ_PORT overrides.
"""

import os

POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
RABBITMQ_PORT = os.environ.get("RABBITMQ_PORT", "5672")

DATABASE_URL = os.environ.get("DATABASE_URL", f"postgresql://postgres:postgres@localhost:{POSTGRES_PORT}/companies")
RABBITMQ_URL = os.environ.get("RABBITMQ_URL", f"amqp://guest:guest@localhost:{RABBITMQ_PORT}/")

QUEUE_NAME = "company-events"
EMBEDDING_DIMENSIONS = 384
