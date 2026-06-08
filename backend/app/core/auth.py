"""FastAPI auth dependencies for Supabase JWTs.

Uses the Supabase JWT signing-key flow: tokens are verified against the
project's JWKS document (fetched from the Supabase auth service), matched
by the token's `kid` header, and decoded with the asymmetric algorithm
declared in the key set. No legacy HS256 shared secret is used.

Two public dependencies are provided:

- ``get_auth_context`` resolves the caller's household after JWT
  verification. This is the standard dependency for all household-scoped
  endpoints.
- ``get_user_context`` verifies the JWT and extracts the user identity
  *without* requiring household membership. Used only by narrow
  onboarding endpoints (household creation, onboarding status).
"""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings
from app.core.database import get_pool
from app.core.jwks import JWKSCache

security = HTTPBearer()

# Module-level JWKS cache. Tests monkeypatch this attribute directly to
# inject a pre-populated cache, so the fetch path stays off the wire.
_jwks_cache: Optional[JWKSCache] = None


def _get_jwks_cache() -> JWKSCache:
    """Lazily create the module-level JWKS cache."""
    global _jwks_cache
    if _jwks_cache is None:
        _jwks_cache = JWKSCache(
            url=settings.jwks_url,
            ttl_seconds=settings.jwks_cache_ttl_seconds,
        )
    return _jwks_cache


@dataclass
class AuthContext:
    """Authenticated user context, resolved from a verified JWT."""
    user_id: UUID
    household_id: UUID
    email: str


@dataclass
class UserContext:
    """Authenticated user identity without household resolution."""
    user_id: UUID
    email: str


async def _verify_jwt_and_extract_claims(
    credentials: HTTPAuthorizationCredentials,
) -> tuple[UUID, str]:
    """Verify a Supabase JWT against JWKS and return (user_id, email).

    Performs: header parsing -> JWKS key lookup -> signature verification
    -> sub + email claim extraction -> UUID parsing and email normalization.
    Raises HTTPException on any failure. No database interaction.
    """
    token = credentials.credentials

    # 1. Read unverified header to get kid + alg
    try:
        header = jwt.get_unverified_header(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token header",
        )

    kid = header.get("kid")
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing key id",
        )

    alg = header.get("alg")
    if not alg:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing algorithm",
        )

    # 2. Resolve the signing key from JWKS
    cache = _get_jwks_cache()
    try:
        jwk_dict = await cache.get_key_by_kid(kid)
    except Exception:
        # JWKS fetch failed (network, 5xx, etc.). Treat as auth infra failure.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to fetch signing keys",
        )
    if jwk_dict is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown signing key",
        )

    # 3. Verify signature + standard claims
    try:
        payload = jwt.decode(
            token,
            jwk_dict,
            algorithms=[alg],
            audience="authenticated",
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    # 4. Extract sub (user id)
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )
    try:
        user_id = UUID(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject is not a valid UUID",
        )

    # 5. Extract and normalize email. Supabase access tokens always include
    # this claim for email/OAuth providers; absence is treated as a 401.
    email_raw = payload.get("email")
    if not isinstance(email_raw, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing email",
        )
    email = email_raw.strip().lower()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing email",
        )

    return user_id, email


async def get_auth_context(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthContext:
    """Verify a Supabase JWT against JWKS and resolve the caller's household.

    Standard dependency for all household-scoped endpoints. Raises 403 if
    the user is not a member of any household.
    """
    user_id, email = await _verify_jwt_and_extract_claims(credentials)

    # Resolve household membership
    pool = get_pool()
    household_id = await pool.fetchval(
        "SELECT household_id FROM household_members WHERE user_id = $1",
        user_id,
    )
    if household_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any household",
        )

    return AuthContext(user_id=user_id, household_id=household_id, email=email)


async def get_user_context(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> UserContext:
    """Verify a Supabase JWT and return user identity without household resolution.

    Used only by the narrow pre-household corridor: household creation,
    onboarding status, and invite lookup/accept. No database interaction.
    """
    user_id, email = await _verify_jwt_and_extract_claims(credentials)
    return UserContext(user_id=user_id, email=email)
