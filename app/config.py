"""Settings, read from environment variables.

The defaults match the template's docker-compose.yml, including its POSTGRES_PORT / RABBITMQ_PORT overrides.
"""

import os
from pathlib import Path

POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
RABBITMQ_PORT = os.environ.get("RABBITMQ_PORT", "5672")

DATABASE_URL = os.environ.get("DATABASE_URL", f"postgresql://postgres:postgres@localhost:{POSTGRES_PORT}/companies")
RABBITMQ_URL = os.environ.get("RABBITMQ_URL", f"amqp://guest:guest@localhost:{RABBITMQ_PORT}/")

QUEUE_NAME = "company-events"
EMBEDDING_DIMENSIONS = 384

# "minilm" (the real model) or "fake" (fast, meaningless vectors, for quick experiments).
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "minilm")
# Where the model files are downloaded on first use. The folder is git-ignored.
MODEL_DIR = Path(os.environ.get("MODEL_DIR", Path(__file__).parent.parent / ".models"))
