"""
API authentication and authorization layer.

Two modes, controlled by AUTH_MODE in .env:

  none      — no auth (default, local dev only)
  apikey    — static API keys per user/team, stored in .env
  windchill — re-use the caller's Windchill credentials to verify access
              and scope results to what that user can see in Windchill

ACL filtering (separate from auth):
  When AUTH_MODE=windchill, each search result is post-filtered by checking
  whether the authenticated Windchill user actually has read permission on
  the retrieved PLM object. This mirrors Windchill's own ACL in the AI layer.

Environment variables:
  AUTH_MODE=none|apikey|windchill

  # For apikey mode — one line per user/team
  API_KEYS=alice:sk-alice-abc123,bob:sk-bob-xyz789,readonly:sk-ro-000

  # For windchill mode — caller supplies their WC credentials in the request
  # (no extra env vars needed; uses WindchillClient to verify)

Usage in routes:
    from backend.api.auth import get_current_user, filter_by_acl
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from backend import config

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

AUTH_MODE: str = os.getenv("AUTH_MODE", "none").lower()

# Parse "user:key,user2:key2" into a dict at startup
_API_KEY_MAP: dict[str, str] = {}
_raw = os.getenv("API_KEYS", "")
if _raw:
    for entry in _raw.split(","):
        entry = entry.strip()
        if ":" in entry:
            username, key = entry.split(":", 1)
            _API_KEY_MAP[key.strip()] = username.strip()


# ── User identity ─────────────────────────────────────────────────────────────

@dataclass
class AuthenticatedUser:
    username: str
    auth_mode: str
    # For windchill mode: pass-through credentials for ACL checks
    wc_username: str = ""
    wc_password: str = ""
    # Roles/groups (populated in windchill mode from WC context membership)
    groups: list[str] = field(default_factory=list)


# ── Auth resolvers ────────────────────────────────────────────────────────────

def _auth_none(
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
) -> AuthenticatedUser:
    """No auth — allow all. Only for local dev."""
    return AuthenticatedUser(username="anonymous", auth_mode="none")


def _auth_apikey(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
) -> AuthenticatedUser:
    """
    Static API key auth.
    Accepts key via:  X-API-Key: sk-alice-abc123
               or:   Authorization: Bearer sk-alice-abc123
    """
    key = x_api_key
    if not key and authorization and authorization.startswith("Bearer "):
        key = authorization.removeprefix("Bearer ").strip()

    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Pass it as X-API-Key header or Authorization: Bearer <key>.",
        )

    username = _API_KEY_MAP.get(key)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )

    log.info(f"[Auth] apikey login: {username}")
    return AuthenticatedUser(username=username, auth_mode="apikey")


def _auth_windchill(
    x_wc_username: Optional[str] = Header(None, alias="X-WC-Username"),
    x_wc_password: Optional[str] = Header(None, alias="X-WC-Password"),
) -> AuthenticatedUser:
    """
    Windchill credential pass-through auth.

    The caller supplies their own Windchill username + password in headers.
    We verify them by making a lightweight OData call ($top=1 on Parts).
    If it succeeds, they're authenticated — and we reuse those credentials
    for ACL filtering on every result.

    In production, use mTLS or a session token instead of password-in-header.
    """
    if not x_wc_username or not x_wc_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Windchill credentials required. "
                "Pass X-WC-Username and X-WC-Password headers."
            ),
        )

    # Verify credentials against Windchill by attempting a minimal fetch
    try:
        import httpx
        resp = httpx.get(
            f"{config.WC_BASE_URL}/Windchill/servlet/odata/ProdMgmt/Parts",
            params={"$top": 1, "$select": "ID", "$format": "json"},
            auth=(x_wc_username, x_wc_password),
            verify=config.WC_SSL_VERIFY,
            timeout=10.0,
        )
        if resp.status_code == 401:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Windchill credentials.",
            )
        if resp.status_code == 403:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Windchill user does not have API access.",
            )
        resp.raise_for_status()
    except HTTPException:
        raise
    except Exception as e:
        log.warning(f"[Auth] Windchill credential check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not reach Windchill to verify credentials: {e}",
        )

    log.info(f"[Auth] windchill login verified: {x_wc_username}")
    return AuthenticatedUser(
        username=x_wc_username,
        auth_mode="windchill",
        wc_username=x_wc_username,
        wc_password=x_wc_password,
    )


# ── FastAPI dependency — import this in routes ────────────────────────────────

def get_current_user(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
    x_wc_username: Optional[str] = Header(None, alias="X-WC-Username"),
    x_wc_password: Optional[str] = Header(None, alias="X-WC-Password"),
) -> AuthenticatedUser:
    """
    FastAPI dependency — resolves the current user based on AUTH_MODE.

    Add to any route:
        user: AuthenticatedUser = Depends(get_current_user)
    """
    if AUTH_MODE == "apikey":
        return _auth_apikey(x_api_key=x_api_key, authorization=authorization)
    if AUTH_MODE == "windchill":
        return _auth_windchill(x_wc_username=x_wc_username, x_wc_password=x_wc_password)
    # AUTH_MODE=none — dev default
    return _auth_none()


# ── ACL filtering — mirror Windchill permissions on search results ────────────

def filter_by_acl(
    chunks: list[dict],
    user: AuthenticatedUser,
) -> list[dict]:
    """
    Post-filter search results to only include objects the user can see
    in Windchill.

    AUTH_MODE=none/apikey  → no filtering (trust the index)
    AUTH_MODE=windchill    → verify each result's object ID against
                             Windchill using the user's own credentials

    This is intentionally conservative: if the Windchill check fails or
    times out for an object, that object is excluded from the response.

    Args:
        chunks: Raw results from semantic_search()
        user:   Authenticated user (carries WC credentials in windchill mode)

    Returns:
        Filtered list — only objects the user is permitted to see.
    """
    if user.auth_mode != "windchill":
        return chunks  # no ACL filtering in apikey/none modes

    allowed = []
    for chunk in chunks:
        if _can_user_read(chunk, user):
            allowed.append(chunk)
        else:
            log.info(
                f"[ACL] Filtered out {chunk['type']} {chunk['number']} "
                f"for user {user.username} — no read access in Windchill"
            )
    return allowed


def _can_user_read(chunk: dict, user: AuthenticatedUser) -> bool:
    """
    Check whether the Windchill user has read access to a specific PLM object.

    Calls Windchill OData with the user's own credentials and tries to fetch
    just the ID of the object. A 403/404 means no access; 200 means allowed.
    """
    obj_id = chunk.get("original_id", "")
    obj_type = chunk.get("type", "")

    # Map internal type to OData collection path
    _type_to_endpoint = {
        "part":          "ProdMgmt/Parts",
        "bom":           "ProdMgmt/Parts",   # BOM parent is a part
        "document":      "DocMgmt/Documents",
        "change_notice": "ChangeMgmt/ChangeNotices",
        "work_order":    "CustomMfg/WorkOrders",  # extend as needed
    }

    endpoint_base = _type_to_endpoint.get(obj_type)
    if not endpoint_base or not obj_id:
        return True  # unknown type — allow through rather than block

    # Strip the BOM- prefix we add during indexing
    wc_id = obj_id.removeprefix("BOM-")

    try:
        import httpx
        url = (
            f"{config.WC_BASE_URL}/Windchill/servlet/odata/"
            f"{endpoint_base}('{wc_id}')"
        )
        resp = httpx.get(
            url,
            params={"$select": "ID", "$format": "json"},
            auth=(user.wc_username, user.wc_password),
            verify=config.WC_SSL_VERIFY,
            timeout=5.0,
        )
        return resp.status_code == 200
    except Exception as e:
        log.warning(f"[ACL] Check failed for {obj_id}: {e} — excluding from results")
        return False
