set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load := true

default: setup

# Install all Python dependencies.
setup:
    uv sync --locked

# Start Postgres (with pgvector) and RabbitMQ, and wait until both are healthy.
up:
    docker compose up -d --wait

# Stop everything and delete the volumes.
down:
    docker compose down -v

# Replay the registry feed onto the company-events queue.
publish:
    uv run python -m producer.publish

# Start the consumer: reads company-events and stores each company. Stop with Ctrl+C.
consume:
    uv run python -m app.consumer

# Start the API on http://localhost:8000 (docs at /docs). Stop with Ctrl+C.
serve:
    uv run uvicorn app.api:app --port 8000

# Run the test suite (uses a separate companies_test database; about 2 minutes).
test:
    uv run pytest -q

# Run only the fast tests (cleaning and storage rules; a few seconds).
test-fast:
    uv run pytest -q tests/test_cleaning.py tests/test_db.py

# Measure API latency over every active company. Needs `just serve` running.
latency:
    uv run python -m scripts.measure_latency

# Load test: 1 to 500 clients at once. Needs `just serve` running; takes a few minutes.
load-test:
    uv run python -m scripts.load_test

# Lint and format check.
lint:
    uv run ruff check .
    uv run ruff format --check .
