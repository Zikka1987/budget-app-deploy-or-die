from typing import TYPE_CHECKING, Any, Union

# Repos accept either a pool connection or an active transaction.
# This lets services pass a transaction object for atomic multi-step operations.
# asyncpg is imported under TYPE_CHECKING so the repositories module can be
# imported in environments where asyncpg is not installed (e.g. pure-function
# and mock-based tests).

if TYPE_CHECKING:
    import asyncpg
    Connection = Union[asyncpg.Connection, asyncpg.pool.Pool]
else:
    Connection = Any
