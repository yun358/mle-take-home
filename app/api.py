"""The service the portal calls: given a company, return its most similar companies.

Run it with `just serve`, then open http://localhost:8000/companies/SYN-001550/similar
(or http://localhost:8000/docs for FastAPI's automatic, clickable documentation).
"""

import re

import psycopg
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from app import db
from app.cleaning import normalise_registration_number
from app.config import DATABASE_URL

# What a registration number looks like after normalising, e.g. SYN-001550.
REGISTRATION_NUMBER_PATTERN = re.compile(r"^[A-Z]+-\d+$")

app = FastAPI(title="Similar companies")


def error(status_code: int, code: str) -> JSONResponse:
    """An error response: the HTTP status plus a short machine-readable code."""
    return JSONResponse(status_code=status_code, content={"error": code})


# The decorator registers the function below as the handler for GET requests to this URL.
# {registration_number} in the URL becomes the function's `registration_number` argument.
@app.get("/companies/{registration_number}/similar")
def similar_companies(registration_number: str, limit: int = Query(default=4, ge=1, le=20)):
    """The `limit` most similar active companies, most similar first, with what each card needs."""
    # FastAPI checks `limit` itself: outside 1..20 it answers 422 before this function runs.
    registration_number = normalise_registration_number(registration_number)
    if not REGISTRATION_NUMBER_PATTERN.match(registration_number):
        return error(400, "invalid_registration_number")

    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=3) as connection:
            company = db.get_company(connection, registration_number)
            if company is None:
                return error(404, "company_not_found")

            if company["embedded_text"] is None:  # e.g. a strike-off seen before the company itself
                similar = []
            else:
                similar = db.find_similar(connection, registration_number, limit)
    except psycopg.OperationalError:  # the database is down or unreachable
        return error(503, "service_unavailable")

    return {
        "registrationNumber": registration_number,
        "status": "struck_off" if company["struck_off"] else "active",
        "similar": [
            {
                "registrationNumber": row["registration_number"],
                "name": row["name"],
                "industry": row["industry"],
                "state": row["state"],
            }
            for row in similar
        ],
    }


@app.get("/health")
def health():
    """200 if the database answers, 503 if not. Useful for monitoring and container health checks."""
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=3) as connection:
            connection.execute("SELECT 1")
    except psycopg.OperationalError:
        return error(503, "service_unavailable")
    return {"status": "ok"}
