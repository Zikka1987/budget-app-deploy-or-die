"""Adapter that wraps a single asyncpg.Connection to behave like asyncpg.Pool.

Used in integration tests so services call pool.acquire() as normal,
but always get the same connection (which is held inside the test's
rollback transaction). Inner conn.transaction() calls become savepoints
automatically (asyncpg behaviour when nesting transactions).
"""


class SingleConnectionPool:
    """Wraps one asyncpg.Connection so it quacks like asyncpg.Pool."""

    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)

    async def close(self):
        pass  # No-op; the test fixture owns the connection lifecycle.


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass  # Do not release; the test transaction owns the connection.
