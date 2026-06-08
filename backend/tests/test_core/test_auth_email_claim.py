"""Tests for the email-claim extraction added to _verify_jwt_and_extract_claims.

Supabase access tokens include `email` for email/OAuth providers. Our auth
layer reads and normalizes that claim and exposes it on both AuthContext
and UserContext. Missing/empty email is a 401.
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


HOUSEHOLD_ID = UUID("33333333-3333-3333-3333-333333333333")


def _int_to_b64url(n: int) -> str:
    length = (n.bit_length() + 7) // 8
    return base64url_encode(n.to_bytes(length, "big")).decode("ascii").rstrip("=")


def _make_es256_keypair(kid: str):
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


class _FakeJWKSCache:
    def __init__(self, keys_by_kid: dict):
        self._keys = keys_by_kid

    async def get_key_by_kid(self, kid: str):
        return self._keys.get(kid)


@pytest.fixture
def signing_key():
    kid = "email-claim-kid"
    private_pem, public_jwk = _make_es256_keypair(kid)
    return private_pem, public_jwk, kid


@pytest.fixture
def jwks(monkeypatch, signing_key):
    _, public_jwk, kid = signing_key
    monkeypatch.setattr(auth_module, "_jwks_cache", _FakeJWKSCache({kid: public_jwk}))


@pytest.fixture
def pool_with_membership(monkeypatch):
    pool = MagicMock()
    pool.fetchval = AsyncMock(return_value=HOUSEHOLD_ID)
    monkeypatch.setattr(auth_module, "get_pool", lambda: pool)
    return pool


def _sign(private_pem: str, kid: str, sub: str, **extra) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "aud": "authenticated",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    payload.update(extra)
    return jwt.encode(payload, private_pem, algorithm="ES256", headers={"kid": kid})


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class TestEmailClaimPopulatesContexts:
    @pytest.mark.asyncio
    async def test_user_context_has_email(self, signing_key, jwks):
        private_pem, _, kid = signing_key
        user_id = uuid4()
        token = _sign(private_pem, kid, sub=str(user_id), email="alice@example.test")

        ctx = await get_user_context(_creds(token))

        assert isinstance(ctx, UserContext)
        assert ctx.user_id == user_id
        assert ctx.email == "alice@example.test"

    @pytest.mark.asyncio
    async def test_auth_context_has_email(
        self, signing_key, jwks, pool_with_membership
    ):
        private_pem, _, kid = signing_key
        user_id = uuid4()
        token = _sign(private_pem, kid, sub=str(user_id), email="bob@example.test")

        ctx = await get_auth_context(_creds(token))

        assert isinstance(ctx, AuthContext)
        assert ctx.user_id == user_id
        assert ctx.household_id == HOUSEHOLD_ID
        assert ctx.email == "bob@example.test"


class TestEmailClaimNormalization:
    @pytest.mark.asyncio
    async def test_uppercase_and_whitespace_normalized(self, signing_key, jwks):
        private_pem, _, kid = signing_key
        token = _sign(
            private_pem, kid, sub=str(uuid4()), email="  Foo@Example.COM  "
        )

        ctx = await get_user_context(_creds(token))

        assert ctx.email == "foo@example.com"


class TestEmailClaimMissing:
    @pytest.mark.asyncio
    async def test_missing_email_returns_401(self, signing_key, jwks):
        private_pem, _, kid = signing_key
        token = _sign(private_pem, kid, sub=str(uuid4()))  # no email key

        with pytest.raises(HTTPException) as exc_info:
            await get_user_context(_creds(token))
        assert exc_info.value.status_code == 401
        assert "email" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_empty_email_returns_401(self, signing_key, jwks):
        private_pem, _, kid = signing_key
        token = _sign(private_pem, kid, sub=str(uuid4()), email="   ")

        with pytest.raises(HTTPException) as exc_info:
            await get_user_context(_creds(token))
        assert exc_info.value.status_code == 401
        assert "email" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_non_string_email_returns_401(self, signing_key, jwks):
        private_pem, _, kid = signing_key
        token = _sign(private_pem, kid, sub=str(uuid4()), email=12345)

        with pytest.raises(HTTPException) as exc_info:
            await get_user_context(_creds(token))
        assert exc_info.value.status_code == 401
