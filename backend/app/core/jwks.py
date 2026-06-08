"""JWKS cache for Supabase JWT signing-key verification.

Fetches the project's JWKS document from the configured URL and caches it
in memory with a TTL. On a kid cache miss (e.g. key rotation), forces a
single refresh before giving up.

The cache is async-safe via an asyncio.Lock so concurrent requests don't
fire multiple parallel fetches.
"""

import asyncio
import time
from typing import Any, Optional

import httpx


class JWKSCache:
    """In-memory JWKS cache with TTL and on-miss refresh."""

    def __init__(self, url: str, ttl_seconds: int = 3600):
        self._url = url
        self._ttl = ttl_seconds
        self._cache: Optional[dict[str, Any]] = None
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_key_by_kid(self, kid: str) -> Optional[dict[str, Any]]:
        """Return the JWK with the given kid, or None if not found.

        First checks the cached JWKS (refreshing if the TTL has elapsed).
        If the kid is not present in the cache, forces a single extra
        refresh in case a key was just rotated in. Returns None if the
        kid is still not present after the refresh.
        """
        keys = await self._get_cached_keys()
        key = self._find_key(keys, kid)
        if key is not None:
            return key

        # Cache miss: force one more refresh then try again.
        await self._force_refresh()
        if self._cache is None:
            return None
        return self._find_key(self._cache.get("keys", []), kid)

    async def _get_cached_keys(self) -> list[dict[str, Any]]:
        """Return the cached keys, refreshing if the TTL has elapsed."""
        async with self._lock:
            if self._cache is None or self._is_stale():
                await self._refresh_locked()
            return self._cache.get("keys", []) if self._cache else []

    async def _force_refresh(self) -> None:
        """Force a JWKS refresh regardless of TTL."""
        async with self._lock:
            await self._refresh_locked()

    async def _refresh_locked(self) -> None:
        """Fetch the JWKS document. Must be called with the lock held."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(self._url)
            response.raise_for_status()
            self._cache = response.json()
            self._fetched_at = time.monotonic()

    def _is_stale(self) -> bool:
        return (time.monotonic() - self._fetched_at) > self._ttl

    @staticmethod
    def _find_key(
        keys: list[dict[str, Any]], kid: str
    ) -> Optional[dict[str, Any]]:
        for key in keys:
            if key.get("kid") == kid:
                return key
        return None
