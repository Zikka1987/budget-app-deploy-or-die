"""Router-level tests for the /api/v1/invites/ endpoints.

Verifies FastAPI dependency wiring: AuthContext vs UserContext usage,
happy-path status codes, and a post-accept integration check showing
that a household-scoped endpoint becomes accessible once the invitee
is added to household_members.
"""

from __future__ import annotations

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


INVITER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
INVITEE_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
HOUSEHOLD_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
INVITE_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
NOW = datetime.now(timezone.utc)
KID = "invites-kid"


# ── Key + token helpers (same pattern as test_onboarding_auth.py) ──


def _int_to_b64url(n: int) -> str:
    length = (n.bit_length() + 7) // 8
    return base64url_encode(n.to_bytes(length, "big")).decode("ascii").rstrip("=")


def _make_es256_keypair(kid: str):
    pk = ec.generate_private_key(ec.SECP256R1())
    pem = pk.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    pub = pk.public_key().public_numbers()
    jwk_ = {
        "kty": "EC",
        "crv": "P-256",
        "x": _int_to_b64url(pub.x),
        "y": _int_to_b64url(pub.y),
        "alg": "ES256",
        "kid": kid,
        "use": "sig",
    }
    return pem, jwk_


PRIVATE_PEM, PUBLIC_JWK = _make_es256_keypair(KID)


def _sign(sub: str, email: str) -> str:
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
    def __init__(self, keys: dict):
        self._keys = keys

    async def get_key_by_kid(self, kid: str):
        return self._keys.get(kid)


def _make_pool(has_household: bool):
    pool = MagicMock()
    pool.fetchval = AsyncMock(
        return_value=HOUSEHOLD_ID if has_household else None
    )
    conn = MagicMock()
    txn_ctx = MagicMock()
    txn_ctx.__aenter__ = AsyncMock(return_value=None)
    txn_ctx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=txn_ctx)
    acq = MagicMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acq)
    return pool


@pytest.fixture
def install_jwks(monkeypatch):
    monkeypatch.setattr(auth_module, "_jwks_cache", _FakeJWKSCache({KID: PUBLIC_JWK}))


@pytest.fixture
def pool_with_household(monkeypatch, install_jwks):
    pool = _make_pool(has_household=True)
    monkeypatch.setattr(database_module, "_pool", pool)
    return pool


@pytest.fixture
def pool_no_household(monkeypatch, install_jwks):
    pool = _make_pool(has_household=False)
    monkeypatch.setattr(database_module, "_pool", pool)
    return pool


@pytest.fixture
def inviter_header():
    return {"Authorization": f"Bearer {_sign(str(INVITER_ID), 'inviter@example.test')}"}


@pytest.fixture
def invitee_header():
    return {"Authorization": f"Bearer {_sign(str(INVITEE_ID), 'invitee@example.test')}"}


def _fake_service(monkeypatch):
    """Patch InviteService inside the router module with an AsyncMock-methods instance."""
    svc = MagicMock()
    svc.create_invite = AsyncMock()
    svc.list_invites = AsyncMock(return_value=[])
    svc.revoke_invite = AsyncMock(return_value=None)
    svc.lookup_invite = AsyncMock()
    svc.accept_invite = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.invites.InviteService",
        MagicMock(return_value=svc),
    )
    return svc


# ══════════════════════════════════════════════════════════════════════
# Auth wiring
# ══════════════════════════════════════════════════════════════════════


class TestAuthWiring:
    @pytest.mark.asyncio
    async def test_no_auth_returns_401_on_all_endpoints(self, install_jwks):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for method, path, body in [
                ("POST",   "/api/v1/invites/",                    {"email": "x@y.z"}),
                ("GET",    "/api/v1/invites/",                    None),
                ("DELETE", f"/api/v1/invites/{INVITE_ID}",        None),
                ("POST",   "/api/v1/invites/lookup",              {"token": "t"}),
                ("POST",   "/api/v1/invites/accept",              {"token": "t", "display_name": "B"}),
            ]:
                resp = await client.request(method, path, json=body)
                assert resp.status_code in (401, 403), (
                    f"{method} {path} -> {resp.status_code}"
                )

    @pytest.mark.asyncio
    async def test_inviter_create_requires_household(
        self, pool_no_household, inviter_header, monkeypatch,
    ):
        """AuthContext dependency rejects callers with no household (403)."""
        _fake_service(monkeypatch)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/invites/",
                json={"email": "invitee@example.test"},
                headers=inviter_header,
            )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_invitee_accept_does_not_require_household(
        self, pool_no_household, invitee_header, monkeypatch,
    ):
        """UserContext dependency — invitee without household reaches the service."""
        svc = _fake_service(monkeypatch)
        svc.accept_invite.return_value = {
            "household": {
                "id": HOUSEHOLD_ID,
                "name": "Family Budget",
                "created_at": NOW,
                "updated_at": NOW,
            },
            "member": {
                "id": uuid4(),
                "household_id": HOUSEHOLD_ID,
                "user_id": INVITEE_ID,
                "display_name": "Bob",
                "role": "member",
                "joined_at": NOW,
            },
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/invites/accept",
                json={"token": "raw", "display_name": "Bob"},
                headers=invitee_header,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["household"]["id"] == str(HOUSEHOLD_ID)
        assert data["member"]["role"] == "member"


# ══════════════════════════════════════════════════════════════════════
# Create / list / revoke (inviter)
# ══════════════════════════════════════════════════════════════════════


class TestInviterEndpoints:
    @pytest.mark.asyncio
    async def test_create_invite_201(
        self, pool_with_household, inviter_header, monkeypatch,
    ):
        svc = _fake_service(monkeypatch)
        expires_at = NOW + timedelta(days=7)
        svc.create_invite.return_value = {
            "id": INVITE_ID,
            "household_id": HOUSEHOLD_ID,
            "invited_by_user_id": INVITER_ID,
            "email": "invitee@example.test",
            "token": "raw-token-abc",
            "status": "pending",
            "expires_at": expires_at,
            "created_at": NOW,
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/invites/",
                json={"email": "invitee@example.test"},
                headers=inviter_header,
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["token"] == "raw-token-abc"
        assert body["email"] == "invitee@example.test"
        assert body["status"] == "pending"
        # Service was called with the normalized email via the request body
        call = svc.create_invite.call_args
        assert call.args[1] == "invitee@example.test"

    @pytest.mark.asyncio
    async def test_list_invites_strips_token_hash(
        self, pool_with_household, inviter_header, monkeypatch,
    ):
        svc = _fake_service(monkeypatch)
        svc.list_invites.return_value = [
            {
                "id": INVITE_ID,
                "email": "invitee@example.test",
                "status": "pending",
                "expires_at": NOW + timedelta(days=7),
                "created_at": NOW,
                "accepted_at": None,
                "revoked_at": None,
            },
        ]
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/invites/", headers=inviter_header
            )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["invites"]) == 1
        # Response schema does not include token / token_hash fields at all
        for inv in body["invites"]:
            assert "token" not in inv
            assert "token_hash" not in inv

    @pytest.mark.asyncio
    async def test_revoke_invite_204(
        self, pool_with_household, inviter_header, monkeypatch,
    ):
        svc = _fake_service(monkeypatch)
        svc.revoke_invite.return_value = None
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete(
                f"/api/v1/invites/{INVITE_ID}", headers=inviter_header,
            )
        assert resp.status_code == 204


# ══════════════════════════════════════════════════════════════════════
# Lookup (invitee)
# ══════════════════════════════════════════════════════════════════════


class TestLookupEndpoint:
    @pytest.mark.asyncio
    async def test_lookup_200(
        self, pool_no_household, invitee_header, monkeypatch,
    ):
        svc = _fake_service(monkeypatch)
        svc.lookup_invite.return_value = {
            "household_name": "Family Budget",
            "email": "invitee@example.test",
            "expires_at": NOW + timedelta(days=7),
            "status": "pending",
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/invites/lookup",
                json={"token": "raw"},
                headers=invitee_header,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["household_name"] == "Family Budget"
        assert body["email"] == "invitee@example.test"


# ══════════════════════════════════════════════════════════════════════
# Post-accept: household endpoints resolve
# ══════════════════════════════════════════════════════════════════════


class TestPostAcceptAuthResolves:
    @pytest.mark.asyncio
    async def test_dashboard_becomes_accessible_once_member(
        self, monkeypatch, install_jwks, invitee_header,
    ):
        """After accept, the same JWT calling /households/me with a pool that
        now returns HOUSEHOLD_ID must succeed (not 403).

        We simulate the post-accept state by seeding a pool where fetchval
        returns HOUSEHOLD_ID for the invitee's user_id.
        """
        pool = _make_pool(has_household=True)
        monkeypatch.setattr(database_module, "_pool", pool)

        # Patch HouseholdRepository used by households router to return a row
        with patch(
            "app.services.household_service.HouseholdRepository"
        ) as MockRepo:
            repo = MockRepo.return_value
            repo.get_household = AsyncMock(return_value={
                "id": HOUSEHOLD_ID,
                "name": "Family Budget",
                "created_at": NOW,
                "updated_at": NOW,
            })
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/households/me", headers=invitee_header
                )
            assert resp.status_code == 200
            assert resp.json()["id"] == str(HOUSEHOLD_ID)
