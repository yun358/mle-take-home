# Similar companies service

A "Similar companies" service for the OneCredit portal, built for the OneCredit MLE take-home (`mle-v2026.11`; the
original brief is the README of [OneCreditMY/mle-take-home](https://github.com/OneCreditMY/mle-take-home)).

```
registry feed ──▶ RabbitMQ (company-events) ──▶ consumer ──▶ Postgres + pgvector ◀── API ◀── portal
                                     clean → embed → store → ack
```

- **Consumer** (`just consume`): reads `company-events`, cleans each message, embeds the business description with
  a multilingual model, keeps the newest version of each company, and acks only after the database commit.
- **API** (`just serve`): `GET /companies/{registrationNumber}/similar` returns the most similar active companies,
  found with a pgvector similarity search, with what the portal needs for each card.

Decisions, assumptions, results and what's left are in [`DESIGN.md`](DESIGN.md).

## Requirements

Docker, [uv](https://docs.astral.sh/uv/) (it installs Python 3.14) and [just](https://github.com/casey/just).
The first run needs internet access to download the embedding model (about 128 MB).

## Run it

You'll use three terminals. Run every command from the project folder.

**1. Install and start the infrastructure** (about a minute):

```bash
just setup      # install Python dependencies
just up         # start Postgres (with pgvector) and RabbitMQ, and wait until both are healthy
```

**2. Start the consumer** in the first terminal and leave it running:

```bash
just consume
```

The first run downloads the model into `.models/` (once). When it's ready it prints:

```
embedding with paraphrase-multilingual-MiniLM-L12-v2-quint8@e8f8c21
waiting for messages on company-events
```

**3. Publish the feed** in a second terminal:

```bash
just publish
```

It prints `published 2518 messages to company-events`. The consumer then prints one line per message, such as
`updated_and_embedded <message id>` or `rejected:invalid_json <message id>`. Embedding the whole feed takes about
2–3 minutes on a laptop CPU; it's done when the lines stop. (Starting the consumer after publishing works too.)

**4. Start the API** in a third terminal:

```bash
just serve
```

**5. Ask for a company's similar companies:**

```bash
curl http://localhost:8000/companies/SYN-001550/similar
```

```json
{
  "registrationNumber": "SYN-001550",
  "status": "active",
  "similar": [
    {"registrationNumber": "SYN-000539", "name": "Seri Sejahtera Food Sdn. Bhd.", "industry": "Food & Beverage", "state": "Johor"},
    ...
  ]
}
```

http://localhost:8000/docs has interactive documentation where you can try any company.

**To stop:** Ctrl+C in each terminal. **To start again from an empty queue and database:** `just down`, then
`just up`.

## Check it worked

After the feed has been processed, the database should hold 2,000 companies (8 struck off, all embedded) and 25
rejected messages (the feed has 30 unusable lines; 6 of them are identical, so they're stored once):

```bash
docker compose exec postgres psql -U postgres -d companies -c "SELECT count(*) AS companies, count(*) FILTER (WHERE struck_off) AS struck_off, count(*) FILTER (WHERE embedding IS NULL) AS not_embedded FROM companies;"
```

```bash
docker compose exec postgres psql -U postgres -d companies -c "SELECT reason, count(*) FROM rejected_messages GROUP BY reason;"
```

The queue is at http://localhost:15672 (user and password `guest`): under Queues → `company-events`, Ready and
Unacked should both be 0. Running `just publish` again changes none of the counts above.

A few more requests to try:

```bash
curl "http://localhost:8000/companies/%20syn-001550%20/similar?limit=2"   # messy input is normalised
curl http://localhost:8000/companies/SYN-000186/similar                 # struck off: "status": "struck_off"
curl http://localhost:8000/companies/SYN-999999/similar                 # 404 company_not_found
curl http://localhost:8000/companies/hello/similar                      # 400 invalid_registration_number
curl http://localhost:8000/health                                       # {"status": "ok"}
```

## Run the tests

Postgres must be running (`just up`). RabbitMQ and the API don't need to be.

```bash
just test        # all tests, about 2–3 minutes (several load the whole feed)
just test-fast   # cleaning and storage rules only, a few seconds
just lint        # ruff check and format check
```

Expect `60 passed`, or `57 passed, 3 skipped` if the model hasn't been downloaded yet (the three real-model tests
skip until `just consume` has run once).

The tests use a separate `companies_test` database in the same Postgres (created automatically and emptied before
each test), so they never touch the data from the steps above. They use a fast, deterministic fake embedder; the
real model is evaluated separately (see `DESIGN.md`).

| Test file | What it checks |
|---|---|
| `tests/test_cleaning.py` | every cleaning rule; the whole feed gives 30 rejections and 2,000 companies |
| `tests/test_db.py` | newer-wins, out-of-order and partial updates, missing timestamps, strike-offs, re-embedding |
| `tests/test_consumer.py` | ack only after saving, failures put back on the queue, the whole feed loaded once and twice |
| `tests/test_api.py` | ordering, exclusions, card fields, error codes, tie shuffling, a full panel for every company |
| `tests/test_embedding.py` | the real model: vector shape and length, English and Malay versions land close |

CI (`.github/workflows/test.yml`) runs `just lint` and the tests on every push, against a pgvector Postgres.

## Measure performance

With the API running:

```bash
just latency     # response times over every active company, one request at a time
just load-test   # 1 to 500 clients at once: throughput, latency percentiles, errors (a few minutes)
```

## Without just

`just` only runs these commands for you:

| `just` | Command |
|---|---|
| `just setup` | `uv sync --locked` |
| `just up` / `just down` | `docker compose up -d --wait` / `docker compose down -v` |
| `just consume` | `uv run python -m app.consumer` |
| `just publish` | `uv run python -m producer.publish` |
| `just serve` | `uv run uvicorn app.api:app --port 8000` |
| `just test` | `uv run pytest -q` |
| `just latency` / `just load-test` | `uv run python -m scripts.measure_latency` / `uv run python -m scripts.load_test` |

`just` reads a `.env` file if there is one; plain `uv run` doesn't, so add `--env-file .env` if you use one.

## Configuration

Environment variables (or a `.env` file):

| Variable | Default | |
|---|---|---|
| `POSTGRES_PORT`, `RABBITMQ_PORT`, `RABBITMQ_UI_PORT` | `5432`, `5672`, `15672` | change if those ports are taken, before `just up` |
| `DATABASE_URL`, `RABBITMQ_URL` | built from the ports above | |
| `EMBEDDING_MODEL` | `minilm` | `fake` for meaningless but instant vectors |
| `MODEL_DIR` | `.models/` | where the model is downloaded |

## Troubleshooting

- **A port is already in use** (`just up` fails, or tests say `password authentication failed`): another Postgres or
  RabbitMQ is running on that port. Put different ports in a `.env` file, for example `POSTGRES_PORT=5433`,
  `RABBITMQ_PORT=5673` and `RABBITMQ_UI_PORT=15673`, then `just down` and `just up`.
- **The model download fails:** check internet access; the consumer retries the download on its next start. A
  partly downloaded file is never used.
- **The API returns 503:** Postgres isn't reachable. Check `docker compose ps`.
- **Recommendations look random:** the consumer may have been run with `EMBEDDING_MODEL=fake`. Run `just down`,
  `just up`, and load the feed again without it.

## API reference

`GET /companies/{registrationNumber}/similar?limit=4`

- `registrationNumber` is normalised the same way as the feed (`" syn-001550 "` works).
- `limit`: how many companies to return, 1–20, default 4.
- Results are the most similar first. Never the company itself, never struck-off companies.
- Companies that are exactly as similar as each other (many share a description) are shuffled on every
  request, so refreshing the page shows other equally good matches.
- Each card has `registrationNumber`, `name`, `industry` and `state`; `industry` and `state` can be `null`.

| Case | Status | Body |
|---|---|---|
| Found | 200 | as above, `"status": "active"` |
| Company is struck off | 200 | same shape, `"status": "struck_off"`: its page still works |
| Company known only from a strike-off (no details) | 200 | `"similar": []` |
| Invalid registration number | 400 | `{"error": "invalid_registration_number"}` |
| Unknown company | 404 | `{"error": "company_not_found"}` |
| `limit` outside 1–20 | 422 | FastAPI's validation error |
| Database unavailable | 503 | `{"error": "service_unavailable"}` |

`GET /health` returns 200 when the database answers, 503 when it doesn't.

## Layout

```
app/
  config.py      settings from environment variables
  models.py      what a message becomes after cleaning
  cleaning.py    raw message → clean record or rejection (pure functions)
  embedding.py   the real model and the fake one for tests
  db.py          all SQL: schema, newer-wins writes, similarity query
  consumer.py    queue → clean → embed → store → ack
  api.py         the HTTP API
tests/           cleaning, storage, consumer, API and model tests
scripts/         latency measurement and load test
producer/        the template's feed publisher (unchanged)
data/feed.jsonl  the registry feed (unchanged)
```
