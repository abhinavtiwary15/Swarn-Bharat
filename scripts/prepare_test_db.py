#!/usr/bin/env python3
"""Idempotently prepare and migrate the test database."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
from alembic import command
from alembic.config import Config


def _get_target_db_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://swarnbharat:swarnbharat@localhost:5432/swarnbharat_test",
    )


async def _create_database_and_extension(test_url: str) -> None:
    clean_url = test_url.replace("postgresql+asyncpg://", "postgresql://")
    parts = urlsplit(clean_url)
    db_name = parts.path.lstrip("/")

    if not db_name.endswith("_test"):
        print(
            f"ERROR: Refusing to prepare database {db_name!r}. "
            "Test database name must strictly end in '_test'.",
            file=sys.stderr,
        )
        sys.exit(1)

    maint_parts = parts._replace(path="/postgres")
    maint_url = urlunsplit(maint_parts)

    print(f"Connecting to maintenance DB to verify {db_name!r}...")
    maint_conn = await asyncpg.connect(maint_url)
    try:
        exists = await maint_conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if not exists:
            print(f"Database {db_name!r} does not exist. Creating...")
            await maint_conn.execute(f'CREATE DATABASE "{db_name}"')
            print(f"Database {db_name!r} created successfully.")
        else:
            print(f"Database {db_name!r} already exists.")
    finally:
        await maint_conn.close()

    target_url = clean_url
    print(f"Connecting to {db_name!r} to ensure pgvector extension...")
    test_conn = await asyncpg.connect(target_url)
    try:
        await test_conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        print("Extension 'vector' verified/installed.")
    finally:
        await test_conn.close()


def _run_migrations(test_url: str) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    backend_dir = repo_root / "backend"
    ini_path = backend_dir / "alembic.ini"

    print("Running Alembic migrations against test database...")
    os.environ["DATABASE_URL"] = test_url
    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(alembic_cfg, "head")
    print("Alembic migrations completed successfully.")


def main() -> None:
    test_url = _get_target_db_url()
    asyncio.run(_create_database_and_extension(test_url))
    _run_migrations(test_url)
    print("Test database preparation complete.")


if __name__ == "__main__":
    main()
