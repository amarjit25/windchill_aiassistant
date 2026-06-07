"""
Windchill REST API client.

Handles authentication (Basic or OAuth2), pagination, and retries.
Returns data shaped to match the same dict structure as the mock JSON files
so the rest of the pipeline (loader.py → indexer) is unchanged.
"""
from __future__ import annotations

import time
from typing import Any, Iterator, Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from backend import config


# ── Session factory ──────────────────────────────────────────────────────────

def _make_session() -> requests.Session:
    """Build a requests Session with retry logic."""
    session = requests.Session()

    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.verify = config.WINDCHILL_SSL_VERIFY
    return session


def _url(path: str) -> str:
    """Construct full URL from base + path."""
    base = config.WINDCHILL_BASE_URL.rstrip("/")
    return base + path


# ── Authentication ───────────────────────────────────────────────────────────

class _BasicAuth:
    def apply(self, session: requests.Session) -> None:
        session.auth = (config.WINDCHILL_USERNAME, config.WINDCHILL_PASSWORD)


class _OAuth2Auth:
    _token: Optional[str] = None
    _expires_at: float = 0.0

    def _fetch_token(self, session: requests.Session) -> str:
        resp = session.post(
            config.WINDCHILL_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": config.WINDCHILL_CLIENT_ID,
                "client_secret": config.WINDCHILL_CLIENT_SECRET,
            },
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._expires_at = time.time() + body.get("expires_in", 3600) - 60
        return self._token

    def apply(self, session: requests.Session) -> None:
        if not self._token or time.time() >= self._expires_at:
            self._fetch_token(session)
        session.headers["Authorization"] = f"Bearer {self._token}"


def _get_auth():
    if config.WINDCHILL_AUTH_TYPE == "oauth2":
        return _OAuth2Auth()
    return _BasicAuth()


# ── Paginated OData fetcher ──────────────────────────────────────────────────

def _fetch_all(path: str, params: Optional[dict] = None) -> list[dict]:
    """
    Fetch all pages from an OData endpoint.

    Windchill OData uses $top/$skip for pagination and returns
    a JSON envelope: {"value": [...], "@odata.nextLink": "..."}
    """
    session = _make_session()
    auth = _get_auth()
    auth.apply(session)

    session.headers.update({
        "Accept": "application/json",
        "Content-Type": "application/json",
    })

    base_params = {"$top": config.WINDCHILL_PAGE_SIZE, "$skip": 0}
    if params:
        base_params.update(params)

    results: list[dict] = []
    url: Optional[str] = _url(path)
    page = 0

    while url:
        if config.WINDCHILL_MAX_PAGES and page >= config.WINDCHILL_MAX_PAGES:
            print(f"[WindchillClient] Reached max pages ({config.WINDCHILL_MAX_PAGES}), stopping.")
            break

        print(f"[WindchillClient] GET {url} (page {page + 1})")
        resp = session.get(url, params=base_params if page == 0 else None, timeout=60)
        resp.raise_for_status()

        body = resp.json()
        page_items = body.get("value", body if isinstance(body, list) else [])
        results.extend(page_items)
        page += 1

        # OData nextLink drives pagination; fall back to skip-based
        next_link = body.get("@odata.nextLink") or body.get("nextLink")
        if next_link:
            url = next_link
        elif len(page_items) == config.WINDCHILL_PAGE_SIZE:
            # No nextLink but full page — advance skip manually
            base_params["$skip"] = page * config.WINDCHILL_PAGE_SIZE
        else:
            url = None

    print(f"[WindchillClient] Fetched {len(results)} items from {path}")
    return results


# ── Public fetchers (one per PLM object type) ────────────────────────────────

def fetch_parts() -> list[dict]:
    """
    Fetch WTPart records from Windchill.

    Maps Windchill OData fields → the same keys used in mock parts.json
    so loader.part_to_chunk() works unchanged.
    """
    raw = _fetch_all(config.WINDCHILL_PARTS_PATH)
    parts = []
    for r in raw:
        parts.append({
            "ID":           r.get("ID") or r.get("id") or r.get("Oid", ""),
            "Number":       r.get("Number") or r.get("PartNumber") or r.get("name", ""),
            "Name":         r.get("Name") or r.get("PartName", ""),
            "State":        _lifecycle_state(r),
            "Version":      r.get("Version") or r.get("versionIdentifier", {}).get("versionId", ""),
            "Revision":     r.get("Revision") or r.get("iterationIdentifier", {}).get("iterationId", ""),
            "Type":         r.get("Type") or r.get("typeId", ""),
            "Material":     _ibaval(r, "Material"),
            "Weight_kg":    _ibaval(r, "Weight_kg") or _ibaval(r, "Weight"),
            "Organization": _org(r),
            "Description":  r.get("Description") or r.get("description", ""),
            "ModifyStamp":  r.get("ModifyStamp") or r.get("modifyStamp") or r.get("lastModified", ""),
        })
    return parts


def fetch_documents() -> list[dict]:
    """Fetch WTDocument records from Windchill."""
    raw = _fetch_all(config.WINDCHILL_DOCUMENTS_PATH)
    docs = []
    for r in raw:
        primary = r.get("PrimaryContent") or r.get("primaryContent") or {}
        docs.append({
            "ID":           r.get("ID") or r.get("Oid", ""),
            "Number":       r.get("Number") or r.get("DocumentNumber", ""),
            "Name":         r.get("Name") or r.get("DocumentName", ""),
            "Type":         r.get("Type") or r.get("documentType", ""),
            "State":        _lifecycle_state(r),
            "Version":      r.get("Version", ""),
            "Author":       r.get("Author") or r.get("creator", ""),
            "Organization": _org(r),
            "Description":  r.get("Description") or r.get("description", ""),
            "ModifyStamp":  r.get("ModifyStamp") or r.get("lastModified", ""),
            "PrimaryContent": {
                "FileName":    primary.get("FileName") or primary.get("fileName", ""),
                "FileSize_kb": primary.get("FileSize_kb") or primary.get("fileSize", ""),
                "TextContent": primary.get("TextContent") or primary.get("textContent", ""),
            },
        })
    return docs


def fetch_bom(part_id: str, part_number: str, part_name: str, part_state: str) -> Optional[dict]:
    """
    Fetch BOM structure for a single part.

    Returns a BOM dict shaped like mock bom.json entries, or None if empty.
    """
    path = config.WINDCHILL_BOM_PATH.replace("{id}", part_id)
    try:
        raw = _fetch_all(path)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        raise

    if not raw:
        return None

    components = []
    for r in raw:
        child = r.get("RelatedPart") or r.get("childPart") or r.get("Part") or {}
        use = r.get("PartUse") or r.get("partUse") or {}
        components.append({
            "Part": {
                "Number": child.get("Number") or child.get("number", ""),
                "Name":   child.get("Name") or child.get("name", ""),
                "State":  _lifecycle_state(child),
            },
            "PartUse": {
                "FindNumber": use.get("FindNumber") or use.get("findNumber", ""),
                "Quantity":   use.get("Quantity") or use.get("quantity", 1),
                "Unit":       use.get("Unit") or use.get("unit", "EA"),
            },
            "Components": [],  # nested BOMs not fetched at this level
        })

    return {
        "ParentPart": {
            "ID":     part_id,
            "Number": part_number,
            "Name":   part_name,
            "State":  part_state,
        },
        "Components": components,
    }


def fetch_change_notices() -> list[dict]:
    """Fetch ChangeOrder / ChangeNotice records from Windchill."""
    raw = _fetch_all(config.WINDCHILL_CN_PATH)
    cns = []
    for r in raw:
        affected_parts = []
        for ap in r.get("AffectedParts") or r.get("affectedParts") or []:
            affected_parts.append({
                "PartNumber": ap.get("PartNumber") or ap.get("partNumber", ""),
                "PartName":   ap.get("PartName") or ap.get("partName", ""),
                "Action":     ap.get("Action") or ap.get("action", ""),
                "Disposition": ap.get("Disposition") or ap.get("disposition", ""),
            })
        affected_docs = []
        for ad in r.get("AffectedDocuments") or r.get("affectedDocuments") or []:
            affected_docs.append({
                "DocNumber": ad.get("DocNumber") or ad.get("documentNumber", ""),
                "DocName":   ad.get("DocName") or ad.get("documentName", ""),
            })
        cns.append({
            "ID":               r.get("ID") or r.get("Oid", ""),
            "Number":           r.get("Number") or r.get("ChangeOrderNumber", ""),
            "Title":            r.get("Title") or r.get("name", ""),
            "State":            _lifecycle_state(r),
            "Priority":         r.get("Priority") or r.get("priority", ""),
            "Category":         r.get("Category") or r.get("category", ""),
            "Description":      r.get("Description") or r.get("description", ""),
            "Reason":           r.get("Reason") or r.get("reason", ""),
            "InitiatedBy":      r.get("InitiatedBy") or r.get("creator", ""),
            "ReleaseDate":      r.get("ReleaseDate") or r.get("releaseDate", ""),
            "EffectivityDate":  r.get("EffectivityDate") or r.get("effectivityDate", ""),
            "AffectedParts":    affected_parts,
            "AffectedDocuments": affected_docs,
        })
    return cns


# ── Helpers ──────────────────────────────────────────────────────────────────

def _lifecycle_state(r: dict) -> str:
    """Extract lifecycle state from various field name conventions."""
    return (
        r.get("State")
        or r.get("state")
        or r.get("lifeCycleState")
        or r.get("lifecycleState")
        or ""
    )


def _org(r: dict) -> str:
    """Extract organization name."""
    org = r.get("Organization") or r.get("organization") or {}
    if isinstance(org, dict):
        return org.get("Name") or org.get("name") or org.get("orgName") or ""
    return str(org)


def _ibaval(r: dict, key: str) -> Any:
    """
    Read an IBA (Instance-Based Attribute) value.
    Windchill often nests custom attributes under 'IBAValues' or 'attributes'.
    """
    # Direct key first
    if key in r:
        return r[key]
    # IBAValues envelope
    iba = r.get("IBAValues") or r.get("ibaValues") or r.get("attributes") or {}
    if isinstance(iba, dict):
        entry = iba.get(key) or iba.get(key.lower()) or {}
        if isinstance(entry, dict):
            return entry.get("value") or entry.get("Value")
        return entry
    return None
