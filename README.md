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

Docker, [uv](https://docs.astral.sh/uv/) (installs Python 3.14) and [just](https://github.com/casey/just).

## Run it

```bash
just setup      # install Python dependencies
just up         # start Postgres (with pgvector) and RabbitMQ
```

In one terminal, start the consumer and leave it running:

```bash
just consume
```

The first run downloads the embedding model (about 128 MB, once, into `.models/`). It prints
`waiting for messages on company-events` when it's ready.

In a second terminal, publish the feed:

```bash
just publish
```

The consumer prints one line per message. Embedding the whole feed takes about 2–3 minutes on a laptop CPU; it's
done when the lines stop (or when the queue shows 0 messages at http://localhost:15672, user and password `guest`).
The order doesn't matter: starting the consumer after `just publish` works too.

In a third terminal, start the API:

```bash
just serve
```

Then ask for a company's similar companies:

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

To start again from an empty queue and database: `just down`, then `just up`.

## API

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

## Tests

```bash
just test        # everything, about 2 minutes (several tests load the whole feed)
just test-fast   # cleaning and storage rules only, a few seconds
just lint        # ruff
```

Tests use a separate `companies_test` database in the same Postgres, so they never touch your data. They use a
fast fake embedder; the tests of the real model run only once it has been downloaded (after `just consume`).

With the API running, `just latency` measures response times over every active company, and `just load-test`
sends requests from 1 to 500 clients at once and reports throughput, latency and errors.

## Configuration

Environment variables (a `.env` file is read by `just`):

| Variable | Default | |
|---|---|---|
| `POSTGRES_PORT`, `RABBITMQ_PORT` | `5432`, `5672` | change if those ports are taken, before `just up` |
| `DATABASE_URL`, `RABBITMQ_URL` | built from the ports above | |
| `EMBEDDING_MODEL` | `minilm` | `fake` for meaningless but instant vectors |
| `MODEL_DIR` | `.models/` | where the model is downloaded |

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
