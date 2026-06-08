"""API/router-level tests for the onboarding auth split.

These tests verify that the FastAPI dependency wiring is correct:
- pre-household endpoints (get_user_context) are accessible without a household
- normal endpoints (get_auth_context) still reject users without a household
- after household creation, normal endpoints work

Uses httpx.AsyncClient against the real FastAPI app with mocked pool and JWKS.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

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
NOW = datetime.now(timezone.utc)

KID = "test-api-kid"


# ── Key generation (same pattern as test_auth.py) ──


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


def _make_pool(has_household: bool):
    """Create a mock pool that returns HOUSEHOLD_ID or None for fetchval.

    Also supports pool.acquire() -> conn with conn.transaction() for service calls.
    """
    pool = MagicMock()
    pool.fetchval = AsyncMock(
        return_value=HOUSEHOLD_ID if has_household else None
    )
    # Support pool.acquire() as async context manager yielding a conn
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
    """Install fake JWKS cache on the auth module."""
    cache = _FakeJWKSCache({KID: PUBLIC_JWK})
    monkeypatch.setattr(auth_module, "_jwks_cache", cache)


@pytest.fixture
def pool_no_household(monkeypatch, install_jwks):
    """Mock pool where user has no household membership."""
    pool = _make_pool(has_household=False)
    monkeypatch.setattr(database_module, "_pool", pool)
    return pool


@pytest.fixture
def pool_with_household(monkeypatch, install_jwks):
    """Mock pool where user has a household membership."""
    pool = _make_pool(has_household=True)
    monkeypatch.setattr(database_module, "_pool", pool)
    return pool


@pytest.fixture
def auth_header():
    token = _sign_token()
    return {"Authorization": f"Bearer {token}"}


# ── Pre-household endpoints ──


class TestPreHouseholdEndpoints:
    """Endpoints using get_user_context: accessible without a household."""

    @pytest.mark.asyncio
    async def test_onboarding_status_accessible_without_household(
        self, pool_no_household, auth_header,
    ):
        with patch(
            "app.services.onboarding_service.OnboardingRepository"
        ) as MockRepo:
            repo = MockRepo.return_value
            repo.get_household_id_for_user = AsyncMock(return_value=None)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/onboarding/status", headers=auth_header)

            assert resp.status_code == 200
            data = resp.json()
            assert data["has_household"] is False
            assert data["is_ready"] is False

    @pytest.mark.asyncio
    async def test_create_household_accessible_without_household(
        self, pool_no_household, auth_header,
    ):
        """POST /households returns 201 with correct shape, not 403."""
        with patch(
            "app.services.household_service.HouseholdRepository"
        ) as MockRepo:
            repo = MockRepo.return_value
            repo.get_member_by_user = AsyncMock(return_value=None)
            repo.create_household = AsyncMock(return_value={
                "id": HOUSEHOLD_ID, "name": "My Home", "created_at": NOW, "updated_at": NOW,
            })
            repo.create_member = AsyncMock(return_value={
                "id": uuid4(), "household_id": HOUSEHOLD_ID, "user_id": USER_ID,
                "display_name": "Andreas", "role": "owner", "joined_at": NOW,
            })
            repo.create_settings = AsyncMock(return_value={
                "id": uuid4(), "household_id": HOUSEHOLD_ID, "currency": "DKK",
                "shift_late_income": False, "late_income_cutoff_day": None,
                "created_at": NOW, "updated_at": NOW,
            })

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/households/",
                    json={"household_name": "My Home", "display_name": "Andreas"},
                    headers=auth_header,
                )

            assert resp.status_code == 201
            data = resp.json()
            assert data["household"]["id"] == str(HOUSEHOLD_ID)
            assert data["household"]["name"] == "My Home"
            assert data["member"]["role"] == "owner"
            assert data["member"]["user_id"] == str(USER_ID)
            assert data["settings"]["currency"] == "DKK"
            assert data["settings"]["shift_late_income"] is False


# ── Normal endpoints still protected ──


class TestNormalEndpointsStillProtected:
    """Endpoints using get_auth_context: must reject users without a household."""

    @pytest.mark.asyncio
    async def test_get_household_me_rejects_no_household(
        self, pool_no_household, auth_header,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/households/me", headers=auth_header)
        assert resp.status_code == 403
        assert "household" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_settings_rejects_no_household(
        self, pool_no_household, auth_header,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/household-settings/", headers=auth_header)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_categories_rejects_no_household(
        self, pool_no_household, auth_header,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/categories/", headers=auth_header)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_dashboard_rejects_no_household(
        self, pool_no_household, auth_header,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/dashboard/summary?year=2026&month=4", headers=auth_header,
            )
        assert resp.status_code == 403


# ── Post-household access ──


class TestPostHouseholdAccess:
    """After household exists, normal endpoints work."""

    @pytest.mark.asyncio
    async def test_get_household_me_succeeds(
        self, pool_with_household, auth_header,
    ):
        with patch(
            "app.services.household_service.HouseholdRepository"
        ) as MockRepo:
            repo = MockRepo.return_value
            repo.get_household = AsyncMock(return_value={
                "id": HOUSEHOLD_ID, "name": "My Home", "created_at": NOW, "updated_at": NOW,
            })

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/households/me", headers=auth_header)

            assert resp.status_code == 200
            assert resp.json()["id"] == str(HOUSEHOLD_ID)

    @pytest.mark.asyncio
    async def test_get_settings_succeeds(
        self, pool_with_household, auth_header,
    ):
        with patch(
            "app.services.household_service.HouseholdRepository"
        ) as MockRepo:
            repo = MockRepo.return_value
            repo.get_settings = AsyncMock(return_value={
                "id": uuid4(), "household_id": HOUSEHOLD_ID, "currency": "DKK",
                "shift_late_income": False, "late_income_cutoff_day": None,
                "created_at": NOW, "updated_at": NOW,
            })

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/household-settings/", headers=auth_header)

            assert resp.status_code == 200
            assert resp.json()["currency"] == "DKK"

    @pytest.mark.asyncio
    async def test_update_settings_succeeds(
        self, pool_with_household, auth_header,
    ):
        with patch(
            "app.services.household_service.HouseholdRepository"
        ) as MockRepo:
            repo = MockRepo.return_value
            repo.get_settings = AsyncMock(return_value={
                "id": uuid4(), "household_id": HOUSEHOLD_ID, "currency": "DKK",
                "shift_late_income": False, "late_income_cutoff_day": None,
                "created_at": NOW, "updated_at": NOW,
            })
            repo.update_settings = AsyncMock(return_value={
                "id": uuid4(), "household_id": HOUSEHOLD_ID, "currency": "DKK",
                "shift_late_income": True, "late_income_cutoff_day": 25,
                "created_at": NOW, "updated_at": NOW,
            })

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.put(
                    "/api/v1/household-settings/",
                    json={"shift_late_income": True, "late_income_cutoff_day": 25},
                    headers=auth_header,
                )

            assert resp.status_code == 200
            assert resp.json()["shift_late_income"] is True


# ── Production onboarding rule ──


class TestProductionOnboardingRule:
    """New household must start with zero categories."""

    @pytest.mark.asyncio
    async def test_new_household_has_zero_categories(
        self, pool_no_household, auth_header,
    ):
        """After POST /households, no categories are auto-created.

        The service only calls create_household, create_member, create_settings.
        CategoryRepository is never imported or used by household_service.
        """
        with patch(
            "app.services.household_service.HouseholdRepository"
        ) as MockHHRepo:
            repo = MockHHRepo.return_value
            repo.get_member_by_user = AsyncMock(return_value=None)
            repo.create_household = AsyncMock(return_value={
                "id": HOUSEHOLD_ID, "name": "My Home", "created_at": NOW, "updated_at": NOW,
            })
            repo.create_member = AsyncMock(return_value={
                "id": uuid4(), "household_id": HOUSEHOLD_ID, "user_id": USER_ID,
                "display_name": "Andreas", "role": "owner", "joined_at": NOW,
            })
            repo.create_settings = AsyncMock(return_value={
                "id": uuid4(), "household_id": HOUSEHOLD_ID, "currency": "DKK",
                "shift_late_income": False, "late_income_cutoff_day": None,
                "created_at": NOW, "updated_at": NOW,
            })

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/households/",
                    json={"household_name": "My Home", "display_name": "Andreas"},
                    headers=auth_header,
                )

            assert resp.status_code == 201
            # Verify only household, member, and settings were created — no category calls
            repo.create_household.assert_awaited_once()
            repo.create_member.assert_awaited_once()
            repo.create_settings.assert_awaited_once()
            # The repo mock tracks all attribute accesses. Verify no category methods exist.
            for call_name in [c[0] for c in repo.method_calls]:
                assert "category" not in call_name.lower(), (
                    f"Unexpected category-related call: {call_name}"
                )
