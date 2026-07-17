"""Fixtures for PostgreSQL-backed integration tests.

The tests deliberately require an explicit URL so a developer database is never
selected by the application's default settings by accident.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text

from academic_cluster.services.database import DatabaseService


def pytest_asyncio_loop_factories(config, item):
    """Use the event loop supported by psycopg async connections on Windows."""

    factory = (
        asyncio.SelectorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
    )
    return {"psycopg-compatible": factory}


@pytest.fixture(scope="session")
def agent_postgres_url() -> str:
    """Return the explicitly opted-in disposable PostgreSQL database URL."""

    url = os.getenv("ACADEMIC_CLUSTER_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "set ACADEMIC_CLUSTER_TEST_DATABASE_URL to a disposable PostgreSQL 16 "
            "database initialized with docker/postgres/init.sql"
        )
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("ACADEMIC_CLUSTER_TEST_DATABASE_URL must use postgresql+asyncpg://")
    return url


@pytest.fixture
async def agent_database(agent_postgres_url: str) -> AsyncIterator[DatabaseService]:
    """Create an isolated service instance and verify the Agent schema exists."""

    database = DatabaseService(agent_postgres_url)
    try:
        async with database.session() as session:
            result = await session.execute(
                text("SELECT to_regclass('public.agent_executions')")
            )
            if result.scalar_one() is None:
                pytest.fail("Agent schema is missing from the integration database")
        yield database
    finally:
        await database.close()
