from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

POSTGRES_URL = os.environ.get("POSTGRES_URL", "postgresql://ra1:ra1@postgres:5432/ra1")

_pool = None


async def init_pool() -> None:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(POSTGRES_URL, min_size=1, max_size=10)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool():
    if _pool is None:
        raise RuntimeError(
            "Database pool not initialized. "
            "Ensure startup event has run and init_pool() was called."
        )
    return _pool


@asynccontextmanager
async def get_connection() -> AsyncIterator[asyncpg.Connection]:
    pool = get_pool()
    conn = await pool.acquire()
    try:
        yield conn
    finally:
        await pool.release(conn)