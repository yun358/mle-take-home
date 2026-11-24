"""All SQL lives here: the schema, the newer-wins writes, and the similarity query."""

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from app.models import CompanyUpdate, Rejected, StrikeOff

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS companies (
    registration_number text PRIMARY KEY,
    name                text,           -- NULL only for a strike-off that arrived before any upsert
    nature_of_business  text,
    state               text,
    industry            text,
    updated_at          timestamptz,    -- NULL = missing, treated as older than everything
    struck_off          boolean NOT NULL DEFAULT false,
    struck_off_at       timestamptz,
    embedded_text       text,           -- exactly what was embedded
    embedding_source    text,           -- 'description' or 'fallback'
    embedding_model     text,           -- which model produced the embedding
    embedding           vector(384)
);

CREATE INDEX IF NOT EXISTS companies_embedding_hnsw
    ON companies USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS rejected_messages (
    id          bigserial PRIMARY KEY,
    message_id  text,
    reason      text NOT NULL,
    body        text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now()
);
"""

# Newer wins. Blank (NULL) fields keep the stored value. The WHERE clause skips older or same-age messages;
# a message with no timestamp compares as NULL, so it never overwrites an existing company.
UPSERT_COMPANY = """
INSERT INTO companies (registration_number, name, nature_of_business, state, industry, updated_at)
VALUES (%(registration_number)s, %(name)s, %(nature_of_business)s, %(state)s, %(industry)s, %(updated_at)s)
ON CONFLICT (registration_number) DO UPDATE SET
    name               = COALESCE(excluded.name, companies.name),
    nature_of_business = COALESCE(excluded.nature_of_business, companies.nature_of_business),
    state              = COALESCE(excluded.state, companies.state),
    industry           = COALESCE(excluded.industry, companies.industry),
    updated_at         = excluded.updated_at,
    struck_off         = false,
    struck_off_at      = NULL
WHERE companies.updated_at IS NULL OR excluded.updated_at > companies.updated_at
RETURNING registration_number
"""

# Keeps all details. If the company is unknown, this inserts a placeholder row (a "tombstone") so that an
# older upsert arriving later can't bring the company back.
STRIKE_OFF_COMPANY = """
INSERT INTO companies (registration_number, updated_at, struck_off, struck_off_at)
VALUES (%(registration_number)s, %(updated_at)s, true, %(updated_at)s)
ON CONFLICT (registration_number) DO UPDATE SET
    struck_off    = true,
    struck_off_at = excluded.updated_at,
    updated_at    = excluded.updated_at
WHERE companies.updated_at IS NULL OR excluded.updated_at > companies.updated_at
RETURNING registration_number
"""


def connect(url: str) -> psycopg.Connection:
    connection = psycopg.connect(url)
    create_schema(connection)
    register_vector(connection)  # needs the vector extension, so it comes after the schema
    return connection


def create_schema(connection: psycopg.Connection) -> None:
    connection.execute(SCHEMA)
    connection.commit()


def upsert_company(connection: psycopg.Connection, update: CompanyUpdate) -> bool:
    """Apply an update if it's newer. Returns True if the row changed."""
    row = connection.execute(
        UPSERT_COMPANY,
        {
            "registration_number": update.registration_number,
            "name": update.name,
            "nature_of_business": update.nature_of_business,
            "state": update.state,
            "industry": update.industry,
            "updated_at": update.updated_at,
        },
    ).fetchone()
    return row is not None


def strike_off_company(connection: psycopg.Connection, strike_off: StrikeOff) -> bool:
    """Mark a company struck off if the event is newer. Returns True if the row changed."""
    row = connection.execute(
        STRIKE_OFF_COMPANY,
        {"registration_number": strike_off.registration_number, "updated_at": strike_off.updated_at},
    ).fetchone()
    return row is not None


def save_rejected(connection: psycopg.Connection, rejected: Rejected, message_id: str | None) -> None:
    connection.execute(
        "INSERT INTO rejected_messages (message_id, reason, body) VALUES (%s, %s, %s)",
        (message_id, rejected.reason, rejected.body),
    )


def get_company(connection: psycopg.Connection, registration_number: str) -> dict | None:
    """Return the stored company as a dict (column name -> value), or None if it isn't stored."""
    # dict_row makes this one query return a dict instead of a tuple, so callers write company["name"].
    cursor = connection.cursor(row_factory=dict_row)
    return cursor.execute(
        """
        SELECT registration_number, name, nature_of_business, state, industry, updated_at, struck_off,
               embedded_text, embedding_model
        FROM companies WHERE registration_number = %s
        """,
        (registration_number,),
    ).fetchone()


def save_embedding(
    connection: psycopg.Connection,
    registration_number: str,
    text: str,
    source: str,
    model_name: str,
    embedding: np.ndarray,
) -> None:
    connection.execute(
        """
        UPDATE companies
        SET embedded_text = %s, embedding_source = %s, embedding_model = %s, embedding = %s
        WHERE registration_number = %s
        """,
        (text, source, model_name, embedding, registration_number),
    )
