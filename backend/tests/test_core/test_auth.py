"""Tests for JWKS-based Supabase JWT verification in app.core.auth.

These tests generate a real ES256 key pair per test, construct a JWK for
the public half, sign a token with the private half, and inject a pre-built
JWKSCache into the auth module so no network calls happen.

The household resolution path (pool.fetchval) is mocked via a simple
MagicMock stand-in so we can verify the happy path and the 403 path
without touching a real database.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from jose.utils import base64url_encode

from app.core import auth as auth_module
from app.core.auth import AuthContext, UserContext, get_auth_context, get_user_context
from app.core.jwks import JWKSCache


HOUSEHOLD_ID = UUID("22222222-2222-2222-2222-222222222222")


# ── Key generation helpers ──


def _int_to_b64url(n: int) -> str:
    """Encode an integer as unpadded base64url (JWK format)."""
    length = (n.bit_length() + 7) // 8
    return base64url_encode(n.to_bytes(length, "big")).decode("ascii").rstrip("=")


def _make_es256_keypair(kid: str):
    """Generate an ES256 key pair and return (private_pem_str, public_jwk_dict)."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_numbers = private_key.public_key().public_numbers()
    public_jwk = {
        "kty": "EC",
        "crv": "P-256",
        "x": _int_to_b64url(public_numbers.x),
        "y": _int_to_b64url(public_numbers.y),
        "alg": "ES256",
        "kid": kid,
        "use": "sig",
    }
    return private_pem, public_jwk


def _sign_token(
    private_pem: str,
    kid: str,
    sub: str,
    aud: str = "authenticated",
    algorithm: str = "ES256",
    expires_in_seconds: int = 3600,
    email: str = "user@example.test",
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "aud": aud,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
        "email": email,
    }
    return jwt.encode(
        payload,
        private_pem,
        algorithm=algorithm,
        headers={"kid": kid},
    )


# ── Fixtures ──


class _FakeJWKSCache:
    """Stand-in for JWKSCache that serves keys from an in-memory dict."""

    def __init__(self, keys_by_kid: dict):
        self._keys = keys_by_kid

    async def get_key_by_kid(self, kid: str):
        return self._keys.get(kid)


@pytest.fixture
def signing_key():
    """Generate an ES256 key pair. Returns (private_pem, public_jwk, kid)."""
    kid = "test-kid-1"
    private_pem, public_jwk = _make_es256_keypair(kid)
    return private_pem, public_jwk, kid


@pytest.fixture
def jwks_with_key(monkeypatch, signing_key):
    """Install a fake JWKSCache on the auth module containing the signing key."""
    _, public_jwk, kid = signing_key
    cache = _FakeJWKSCache({kid: public_jwk})
    monkeypatch.setattr(auth_module, "_jwks_cache", cache)
    return cache


@pytest.fixture
def empty_jwks(monkeypatch):
    """Install a fake JWKSCache with no keys - every kid lookup returns None."""
    cache = _FakeJWKSCache({})
    monkeypatch.setattr(auth_module, "_jwks_cache", cache)
    return cache


@pytest.fixture
def fake_pool_with_membership(monkeypatch):
    """Mock get_pool() to return a pool whose fetchval returns HOUSEHOLD_ID."""
    pool = MagicMock()
    pool.fetchval = AsyncMock(return_value=HOUSEHOLD_ID)
    monkeypatch.setattr(auth_module, "get_pool", lambda: pool)
    return pool


@pytest.fixture
def fake_pool_without_membership(monkeypatch):
    """Mock get_pool() to return a pool whose fetchval returns None."""
    pool = MagicMock()
    pool.fetchval = AsyncMock(return_value=None)
    monkeypatch.setattr(auth_module, "get_pool", lambda: pool)
    return pool


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# ── Happy path ──


class TestJWKSVerificationHappyPath:
    @pytest.mark.asyncio
    async def test_valid_token_resolves_household(
        self, signing_key, jwks_with_key, fake_pool_with_membership
    ):
        private_pem, _, kid = signing_key
        user_id = uuid4()
        token = _sign_token(private_pem, kid, sub=str(user_id))

        ctx = await get_auth_context(_creds(token))

        assert isinstance(ctx, AuthContext)
        assert ctx.user_id == user_id
        assert ctx.household_id == HOUSEHOLD_ID
        fake_pool_with_membership.fetchval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_household_lookup_uses_sub_uuid(
        self, signing_key, jwks_with_key, fake_pool_with_membership
    ):
        private_pem, _, kid = signing_key
        user_id = uuid4()
        token = _sign_token(private_pem, kid, sub=str(user_id))

        await get_auth_context(_creds(token))

        # The fetchval call should receive the parsed UUID, not the raw string
        call_args = fake_pool_with_membership.fetchval.call_args
        assert call_args.args[1] == user_id


# ── Signature and header failures ──


class TestJWKSVerificationFailures:
    @pytest.mark.asyncio
    async def test_missing_kid_header_returns_401(
        self, signing_key, jwks_with_key, fake_pool_with_membership
    ):
        """A token without a kid header cannot be verified against JWKS."""
        private_pem, _, _ = signing_key
        # Sign without a kid header
        payload = {
            "sub": str(uuid4()),
            "aud": "authenticated",
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
            "email": "user@example.test",
        }
        token = jwt.encode(payload, private_pem, algorithm="ES256")

        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(_creds(token))
        assert exc_info.value.status_code == 401
        assert "key id" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_unknown_kid_returns_401(
        self, signing_key, empty_jwks, fake_pool_with_membership
    ):
        """A token with a kid not in the JWKS returns 401."""
        private_pem, _, kid = signing_key
        token = _sign_token(private_pem, kid, sub=str(uuid4()))

        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(_creds(token))
        assert exc_info.value.status_code == 401
        assert "unknown signing key" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_signature_mismatch_returns_401(
        self, monkeypatch, fake_pool_with_membership
    ):
        """Token signed by key A, JWKS serves key B under the same kid."""
        kid = "rotated-kid"
        private_pem_a, _ = _make_es256_keypair(kid)
        _, public_jwk_b = _make_es256_keypair(kid)
        # Serve the WRONG public key under the same kid
        monkeypatch.setattr(
            auth_module,
            "_jwks_cache",
            _FakeJWKSCache({kid: public_jwk_b}),
        )
        token = _sign_token(private_pem_a, kid, sub=str(uuid4()))

        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(_creds(token))
        assert exc_info.value.status_code == 401
        assert "invalid" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_expired_token_returns_401(
        self, signing_key, jwks_with_key, fake_pool_with_membership
    ):
        private_pem, _, kid = signing_key
        token = _sign_token(
            private_pem, kid, sub=str(uuid4()), expires_in_seconds=-10,
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(_creds(token))
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_audience_returns_401(
        self, signing_key, jwks_with_key, fake_pool_with_membership
    ):
        private_pem, _, kid = signing_key
        token = _sign_token(
            private_pem, kid, sub=str(uuid4()), aud="not-authenticated",
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(_creds(token))
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_token_returns_401(
        self, jwks_with_key, fake_pool_with_membership
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(_creds("not.a.valid.jwt"))
        assert exc_info.value.status_code == 401
        assert "header" in exc_info.value.detail.lower()


# ── Claim validation failures ──


class TestClaimValidation:
    @pytest.mark.asyncio
    async def test_missing_sub_returns_401(
        self, signing_key, jwks_with_key, fake_pool_with_membership
    ):
        """A token with no sub claim cannot identify a user."""
        private_pem, _, kid = signing_key
        payload = {
            "aud": "authenticated",
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
            "email": "user@example.test",
        }
        token = jwt.encode(payload, private_pem, algorithm="ES256", headers={"kid": kid})

        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(_creds(token))
        assert exc_info.value.status_code == 401
        assert "subject" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_non_uuid_sub_returns_401(
        self, signing_key, jwks_with_key, fake_pool_with_membership
    ):
        private_pem, _, kid = signing_key
        token = _sign_token(private_pem, kid, sub="not-a-uuid")

        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(_creds(token))
        assert exc_info.value.status_code == 401
        assert "uuid" in exc_info.value.detail.lower()


# ── Household resolution ──


class TestHouseholdResolution:
    @pytest.mark.asyncio
    async def test_user_without_household_returns_403(
        self, signing_key, jwks_with_key, fake_pool_without_membership
    ):
        """Token is valid but the user is not a member of any household."""
        private_pem, _, kid = signing_key
        user_id = uuid4()
        token = _sign_token(private_pem, kid, sub=str(user_id))

        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(_creds(token))
        assert exc_info.value.status_code == 403
        assert "household" in exc_info.value.detail.lower()


# ── JWKS fetch infra failures ──


class TestJWKSInfraFailures:
    @pytest.mark.asyncio
    async def test_jwks_fetch_exception_returns_503(
        self, monkeypatch, signing_key, fake_pool_with_membership
    ):
        """If the JWKS cache raises on lookup, the auth dep returns 503."""
        private_pem, _, kid = signing_key

        class RaisingCache:
            async def get_key_by_kid(self, kid: str):
                raise RuntimeError("network down")

        monkeypatch.setattr(auth_module, "_jwks_cache", RaisingCache())
        token = _sign_token(private_pem, kid, sub=str(uuid4()))

        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(_creds(token))
        assert exc_info.value.status_code == 503


# ── JWKSCache behavior ──


class TestJWKSCache:
    @pytest.mark.asyncio
    async def test_returns_matched_key(self):
        kid = "k1"
        _, jwk1 = _make_es256_keypair(kid)
        cache = JWKSCache(url="https://example.invalid/jwks")
        # Bypass HTTP fetch by injecting state directly
        cache._cache = {"keys": [jwk1]}
        cache._fetched_at = 1e18  # far future, never stale
        result = await cache.get_key_by_kid(kid)
        assert result is not None
        assert result["kid"] == kid

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_kid_after_refresh(self, monkeypatch):
        """On a kid cache miss, the cache performs exactly one refresh and then gives up."""
        cache = JWKSCache(url="https://example.invalid/jwks")
        cache._cache = {"keys": []}
        cache._fetched_at = 1e18

        refresh_count = 0

        async def fake_refresh():
            nonlocal refresh_count
            refresh_count += 1
            # Simulate a refresh that still returns no keys
            cache._cache = {"keys": []}

        monkeypatch.setattr(cache, "_force_refresh", fake_refresh)
        result = await cache.get_key_by_kid("nonexistent")
        assert result is None
        assert refresh_count == 1


# ── get_user_context (pre-household auth) ──


class TestGetUserContext:
    """Tests for get_user_context: JWT verification without household resolution."""

    @pytest.mark.asyncio
    async def test_valid_token_returns_user_context(
        self, signing_key, jwks_with_key,
    ):
        """A valid JWT yields UserContext with no pool interaction."""
        private_pem, _, kid = signing_key
        user_id = uuid4()
        token = _sign_token(private_pem, kid, sub=str(user_id))

        ctx = await get_user_context(_creds(token))

        assert isinstance(ctx, UserContext)
        assert ctx.user_id == user_id
        # Confirm no household_id attribute
        assert not hasattr(ctx, "household_id")

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(
        self, jwks_with_key,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_user_context(_creds("not.a.valid.jwt"))
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_household_still_succeeds(
        self, signing_key, jwks_with_key, fake_pool_without_membership,
    ):
        """Unlike get_auth_context, user without a household does NOT get 403."""
        private_pem, _, kid = signing_key
        user_id = uuid4()
        token = _sign_token(private_pem, kid, sub=str(user_id))

        ctx = await get_user_context(_creds(token))

        assert isinstance(ctx, UserContext)
        assert ctx.user_id == user_id
        # Pool was never consulted
        fake_pool_without_membership.fetchval.assert_not_awaited()
