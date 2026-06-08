"""API/router-level tests for search endpoints.

Tests verify auth wiring (401 without token) and response shape
for both receipt and transaction search.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from jose import jwt
from jose.utils import base64url_encode

from app.core import auth as auth_module
from app.core import database as database_module
from app.main import app


USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
HOUSEHOLD_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CATEGORY_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
NOW = datetime.now(timezone.utc)

KID = "test-search-kid"


# ── Key generation (same pattern as test_onboarding_auth.py) ──


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


PRIVATE_PEM, PUBLIC_JWK = _make_es256_keypair(KID)


def _sign_token(sub: str = str(USER_ID), email: str = "user@example.test") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "aud": "authenticated",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "email": email,
    }
    return jwt.encode(payload, PRIVATE_PEM, algorithm="ES256", headers={"kid": KID})


class _FakeJWKSCache:
    def __init__(self, keys_by_kid: dict):
        self._keys = keys_by_kid

    async def get_key_by_kid(self, kid: str):
        return self._keys.get(kid)


# ── Fixtures ──


def _make_pool():
    pool = MagicMock()
    pool.fetchval = AsyncMock(return_value=HOUSEHOLD_ID)
    conn = MagicMock()
    txn_ctx = MagicMock()
    txn_ctx.__aenter__ = AsyncMock(return_value=None)
    txn_ctx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=txn_ctx)
    acq_ctx = MagicMock()
    acq_ctx.__aenter__ = AsyncMock(return_value=conn)
    acq_ctx.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acq_ctx)
    return pool


@pytest.fixture
def install_jwks(monkeypatch):
    cache = _FakeJWKSCache({KID: PUBLIC_JWK})
    monkeypatch.setattr(auth_module, "_jwks_cache", cache)


@pytest.fixture
def pool_with_household(monkeypatch, install_jwks):
    pool = _make_pool()
    monkeypatch.setattr(database_module, "_pool", pool)
    return pool


@pytest.fixture
def auth_header():
    token = _sign_token()
    return {"Authorization": f"Bearer {token}"}


# ── Auth tests (401 without token) ──


class TestSearchAuth:
    @pytest.mark.asyncio
    async def test_search_receipts_unauthenticated_returns_401(
        self, pool_with_household,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/search/receipts")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_search_transactions_unauthenticated_returns_401(
        self, pool_with_household,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/search/transactions")
        assert resp.status_code == 401


# ── Response shape tests ──


class TestSearchResponseShape:
    @pytest.mark.asyncio
    async def test_search_receipts_response_shape(
        self, pool_with_household, auth_header,
    ):
        mock_result = {
            "results": [
                {
                    "id": UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
                    "store_name": "Netto",
                    "receipt_date": date(2026, 4, 10),
                    "total_amount": Decimal("245.50"),
                    "status": "posted",
                    "created_at": NOW,
                }
            ],
            "total": 1,
        }
        with patch(
            "app.services.search_service.SearchRepository"
        ) as MockRepo:
            repo = MockRepo.return_value
            repo.search_receipts = AsyncMock(
                return_value=(mock_result["results"], 1)
            )

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/api/v1/search/receipts", headers=auth_header
                )

        assert resp.status_code == 200
        body = resp.json()
        assert "results" in body
        assert "total" in body
        assert body["total"] == 1
        assert isinstance(body["results"], list)
        assert len(body["results"]) == 1
        assert body["results"][0]["store_name"] == "Netto"

    @pytest.mark.asyncio
    async def test_search_transactions_response_shape(
        self, pool_with_household, auth_header,
    ):
        mock_result = {
            "results": [
                {
                    "id": UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
                    "type": "expense",
                    "source": "receipt",
                    "category_id": CATEGORY_ID,
                    "category_name": "Dagligvarer",
                    "amount": Decimal("245.50"),
                    "description": "Netto purchase",
                    "transaction_date": date(2026, 4, 10),
                    "effective_date": date(2026, 4, 10),
                    "store_name": "Netto",
                    "created_at": NOW,
                }
            ],
            "total": 1,
        }
        with patch(
            "app.services.search_service.SearchRepository"
        ) as MockRepo:
            repo = MockRepo.return_value
            repo.search_transactions = AsyncMock(
                return_value=(mock_result["results"], 1)
            )

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/api/v1/search/transactions", headers=auth_header
                )

        assert resp.status_code == 200
        body = resp.json()
        assert "results" in body
        assert "total" in body
        assert body["total"] == 1
        assert isinstance(body["results"], list)
        assert len(body["results"]) == 1
        assert body["results"][0]["category_name"] == "Dagligvarer"
        assert body["results"][0]["store_name"] == "Netto"
