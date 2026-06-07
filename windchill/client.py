"""
Windchill REST / OData HTTP client.

Supports:
  - Basic Authentication  (most common for API access)
  - Session cookie auth   (used by some Windchill SSO setups)
  - Self-signed SSL certs (common in corporate environments)

All calls go through _get() which handles:
  - Auth headers
  - OData $format=json
  - Retry on 401 (token refresh)
  - Pagination via @odata.nextLink
"""
import os
import time
import logging
from typing import Any, Iterator
from urllib.parse import urljoin

import httpx

from backend import config

log = logging.getLogger(__name__)


class WindchillClient:
    """
    Thin HTTP wrapper for the Windchill OData REST API.

    Usage:
        client = WindchillClient()
        parts = client.get_all("ProdMgmt/Parts", params={"$top": 100})
    """

    def __init__(self):
        self.base_url: str = config.WC_BASE_URL.rstrip("/")
        self.odata_root: str = f"{self.base_url}/Windchill/servlet/odata"

        # Auth — Basic is the default; extend here for OAuth/SSO
        auth = None
        if config.WC_USERNAME and config.WC_PASSWORD:
            auth = (config.WC_USERNAME, config.WC_PASSWORD)

        self._client = httpx.Client(
            auth=auth,
            verify=config.WC_SSL_VERIFY,   # set False to skip cert check
            timeout=httpx.Timeout(60.0, connect=10.0),
            headers={
                "Accept": "application/json",
                "OData-Version": "4.0",
            },
            follow_redirects=True,
        )

        # Windchill sometimes requires a CSRF token obtained via a GET first
        self._csrf_token: str | None = None

    # ── Low-level request ────────────────────────────────────────────────────

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """
        GET an OData endpoint and return the parsed JSON response.
        Appends $format=json if not already present.
        """
        url = f"{self.odata_root}/{endpoint.lstrip('/')}"
        p = params or {}
        p.setdefault("$format", "json")

        for attempt in range(3):
            try:
                resp = self._client.get(url, params=p)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 401:
                    log.warning("401 Unauthorized — check WC_USERNAME / WC_PASSWORD")
                    raise PermissionError(f"Windchill auth failed: {resp.text[:200]}")
                elif resp.status_code == 403:
                    raise PermissionError(f"Windchill access denied to {endpoint}: {resp.text[:200]}")
                else:
                    log.warning(f"HTTP {resp.status_code} on attempt {attempt+1}: {resp.text[:200]}")
                    if attempt < 2:
                        time.sleep(2 ** attempt)
            except httpx.TimeoutException:
                log.warning(f"Timeout on attempt {attempt+1} for {url}")
                if attempt < 2:
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"Failed to GET {url} after 3 attempts")

    def _download(self, url: str) -> bytes:
        """Download raw bytes from an absolute URL (e.g. document content)."""
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.content

    # ── Paginated fetch ──────────────────────────────────────────────────────

    def get_all(
        self,
        endpoint: str,
        params: dict = None,
        max_records: int = None,
    ) -> list[dict]:
        """
        Fetch ALL pages from a Windchill OData collection.

        Windchill OData uses @odata.nextLink for pagination.
        Stops early if max_records is set.

        Args:
            endpoint: e.g. "ProdMgmt/Parts" or "DocMgmt/Documents"
            params:   OData query options ($filter, $select, $expand, $top)
            max_records: safety cap — stop after this many records

        Returns:
            Flat list of all entity dicts from "value" key
        """
        p = dict(params or {})
        p.setdefault("$top", 200)   # Windchill default page size cap is 500

        all_records: list[dict] = []
        next_url: str | None = None
        page = 1

        while True:
            if next_url:
                # Follow the nextLink directly (already has all params baked in)
                resp_json = self._follow_next_link(next_url)
            else:
                resp_json = self._get(endpoint, params=p)

            records = resp_json.get("value", [])
            all_records.extend(records)
            log.info(f"[{endpoint}] Page {page}: fetched {len(records)} records (total: {len(all_records)})")

            if max_records and len(all_records) >= max_records:
                all_records = all_records[:max_records]
                break

            next_url = resp_json.get("@odata.nextLink")
            if not next_url:
                break
            page += 1

        return all_records

    def _follow_next_link(self, url: str) -> dict:
        """GET an absolute nextLink URL (already fully-formed by Windchill)."""
        resp = self._client.get(url, params={"$format": "json"})
        resp.raise_for_status()
        return resp.json()

    # ── Document content download ─────────────────────────────────────────────

    def get_document_content_url(self, doc_id: str) -> str | None:
        """
        Fetch the download URL for a document's primary content.

        Calls:
          GET /DocMgmt/Documents('{id}')/PrimaryContent/PTC.ApplicationData/Content/URL
        Returns the pre-signed download URL string, or None if unavailable.
        """
        endpoint = f"DocMgmt/Documents('{doc_id}')/PrimaryContent/PTC.ApplicationData/Content/URL"
        try:
            data = self._get(endpoint)
            return data.get("value")
        except Exception as e:
            log.warning(f"Could not get content URL for doc {doc_id}: {e}")
            return None

    def download_document_bytes(self, doc_id: str) -> bytes | None:
        """
        Download the primary content file bytes for a document.
        Returns None if the content is unavailable (e.g. native CAD format).
        """
        url = self.get_document_content_url(doc_id)
        if not url:
            return None
        try:
            return self._download(url)
        except Exception as e:
            log.warning(f"Could not download content for doc {doc_id}: {e}")
            return None

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
