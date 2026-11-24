"""Shared test setup: a separate `companies_test` database, emptied before every test.

Tests never touch the real `companies` database, so running them doesn't wipe your data.
"""

import os

import psycopg
import pytest

from app import db
from app.config import POSTGRES_PORT
from app.embedding import FakeEmbedder

ADMIN_URL = f"postgresql://postgres:postgres@localhost:{POSTGRES_PORT}/postgres"
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", f"postgresql://postgres:postgres@localhost:{POSTGRES_PORT}/companies_test"
)


# A fixture is setup code: a test names it as an argument, and pytest runs it and passes in the result.


@pytest.fixture(scope="session")  # runs once per test run
def test_database_url() -> str:
    # CREATE DATABASE can't run inside a transaction, hence autocommit=True.
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = 'companies_test'").fetchone()
        if not exists:
            admin.execute("CREATE DATABASE companies_test")
    return TEST_DATABASE_URL


@pytest.fixture  # runs before every test that asks for `connection`
def connection(test_database_url):
    connection = db.connect(test_database_url)
    connection.execute("TRUNCATE companies, rejected_messages")
    connection.commit()
    yield connection  # the test runs here; the line after runs when it finishes
    connection.close()


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()
