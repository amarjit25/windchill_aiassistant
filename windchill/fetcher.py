"""
High-level fetchers for each PLM object type from Windchill OData.

Each function returns a list of dicts in the same shape as the mock JSON
so the existing data/loader.py converters work without modification.

Windchill OData domains used:
  ProdMgmt   — Parts, BOM
  DocMgmt    — Documents and primary content
  ChangeMgmt — Change Notices, Change Orders, Problem Reports
"""
import logging
from typing import Any

from windchill.client import WindchillClient

log = logging.getLogger(__name__)


# ── Parts (WTPart) ────────────────────────────────────────────────────────────

def fetch_parts(
    client: WindchillClient,
    modified_since: str = None,
    states: list[str] = None,
    max_records: int = None,
) -> list[dict]:
    """
    Fetch WTPart records from Windchill.

    Args:
        modified_since: ISO-8601 timestamp — only fetch parts modified after this
                        e.g. "2024-01-01T00:00:00Z"  (for incremental sync)
        states:         List of lifecycle states to include
                        e.g. ["RELEASED", "INWORK"]   (None = all states)
        max_records:    Safety cap on total records fetched

    Returns:
        List of part dicts (same shape as mock_data/parts.json "value" array)
    """
    params = {
        "$select": (
            "ID,Number,Name,State,Version,Revision,Type,"
            "Description,ModifyStamp,CreatedDate"
        ),
        "$orderby": "ModifyStamp desc",
    }

    filters = []
    if modified_since:
        filters.append(f"ModifyStamp gt {modified_since}")
    if states:
        # OData: State eq 'RELEASED' or State eq 'INWORK'
        state_filter = " or ".join(f"State eq '{s}'" for s in states)
        filters.append(f"({state_filter})")

    if filters:
        params["$filter"] = " and ".join(filters)

    log.info(f"[Parts] Fetching with params: {params}")
    parts = client.get_all("ProdMgmt/Parts", params=params, max_records=max_records)
    log.info(f"[Parts] Fetched {len(parts)} parts from Windchill")
    return parts


# ── BOM (Bill of Materials) ───────────────────────────────────────────────────

def fetch_bom(client: WindchillClient, part_id: str, levels: int = 3) -> dict | None:
    """
    Fetch the BOM tree for a specific part using GetBOM action.

    Args:
        part_id:  The Windchill OID e.g. "OR:wt.part.WTPart:12345"
        levels:   How many BOM levels deep to expand (max ~5 recommended)

    Returns:
        BOM dict in the same shape as mock_data/bom.json "BOMs" entries,
        or None if the part has no BOM.
    """
    # URL-encode the OID for use as an OData key
    encoded_id = part_id.replace(":", "%3A")

    endpoint = (
        f"ProdMgmt/Parts('{encoded_id}')/PTC.ProdMgmt.GetBOM"
        f"?$expand=Components($expand=Part($select=ID,Number,Name,State),"
        f"PartUse($select=Quantity,Unit,ReferenceDesignator,FindNumber);"
        f"$levels={levels})"
    )

    try:
        data = client._get(endpoint)
        # Wrap into the same shape as the mock BOM entry
        return {
            "ParentPart": {
                "ID": part_id,
                "Number": data.get("Number", ""),
                "Name": data.get("Name", ""),
                "State": data.get("State", ""),
            },
            "Components": data.get("Components", []),
        }
    except Exception as e:
        log.warning(f"[BOM] Could not fetch BOM for {part_id}: {e}")
        return None


def fetch_boms_for_assemblies(
    client: WindchillClient,
    parts: list[dict],
    levels: int = 3,
    max_assemblies: int = 20,
) -> list[dict]:
    """
    Fetch BOMs for the top-level assembly parts (Type == 'Assembly').

    Skips leaf parts and limits to max_assemblies to avoid excessive API calls.
    """
    assemblies = [
        p for p in parts
        if p.get("Type", "").lower() in ("assembly", "assemblies")
    ][:max_assemblies]

    log.info(f"[BOM] Fetching BOMs for {len(assemblies)} assemblies")
    boms = []
    for assy in assemblies:
        bom = fetch_bom(client, assy["ID"], levels=levels)
        if bom:
            boms.append(bom)
    return boms


# ── Documents (WTDocument) ────────────────────────────────────────────────────

def fetch_documents(
    client: WindchillClient,
    modified_since: str = None,
    doc_types: list[str] = None,
    max_records: int = None,
    download_content: bool = False,
) -> list[dict]:
    """
    Fetch WTDocument records and optionally their primary content.

    Args:
        modified_since:    ISO-8601 timestamp for delta sync
        doc_types:         Filter by document type name
                           e.g. ["Specification", "Manual", "Report"]
        max_records:       Safety cap
        download_content:  If True, download and embed the actual file text
                           (only works for PDF/text; not native CAD)

    Returns:
        List of document dicts matching the mock_data/documents.json shape
    """
    params = {
        "$select": (
            "ID,Number,Name,State,Version,Type,Description,"
            "Organization,ModifyStamp"
        ),
        "$expand": "PrimaryContent($select=FileName,Format,FileSize)",
        "$orderby": "ModifyStamp desc",
    }

    filters = []
    if modified_since:
        filters.append(f"ModifyStamp gt {modified_since}")
    if doc_types:
        type_filter = " or ".join(f"Type/Name eq '{t}'" for t in doc_types)
        filters.append(f"({type_filter})")

    if filters:
        params["$filter"] = " and ".join(filters)

    log.info(f"[Docs] Fetching with params: {params}")
    docs = client.get_all("DocMgmt/Documents", params=params, max_records=max_records)
    log.info(f"[Docs] Fetched {len(docs)} documents")

    if download_content:
        docs = _enrich_with_content(client, docs)

    return docs


def _enrich_with_content(client: WindchillClient, docs: list[dict]) -> list[dict]:
    """
    For each document, attempt to download the primary content and extract text.
    Falls back gracefully for unsupported formats (native CAD, etc.).
    """
    try:
        import io
        import pypdf          # PDF text extraction
    except ImportError:
        log.warning("[Docs] pypdf not installed — skipping content download. pip install pypdf")
        return docs

    enriched = []
    for doc in docs:
        doc_id = doc.get("ID", "")
        primary = doc.get("PrimaryContent") or {}
        fmt = (primary.get("Format") or "").lower()

        text_content = None

        # Only attempt PDF download (not native CAD like .prt, .asm, .sldprt)
        if "pdf" in fmt:
            raw = client.download_document_bytes(doc_id)
            if raw:
                try:
                    reader = pypdf.PdfReader(io.BytesIO(raw))
                    pages = [p.extract_text() or "" for p in reader.pages]
                    text_content = "\n".join(pages)[:10000]  # cap at 10K chars
                    log.info(f"[Docs] Extracted {len(text_content)} chars from {doc['Number']}")
                except Exception as e:
                    log.warning(f"[Docs] PDF parse failed for {doc['Number']}: {e}")
        elif "text" in fmt or "plain" in fmt:
            raw = client.download_document_bytes(doc_id)
            if raw:
                text_content = raw.decode("utf-8", errors="replace")[:10000]

        # Inject text content into the structure (matches mock shape)
        if text_content:
            doc.setdefault("PrimaryContent", {})["TextContent"] = text_content

        enriched.append(doc)

    return enriched


# ── Change Management ─────────────────────────────────────────────────────────

def fetch_change_notices(
    client: WindchillClient,
    modified_since: str = None,
    states: list[str] = None,
    max_records: int = None,
) -> list[dict]:
    """
    Fetch ChangeNotice (WTChangeOrder2) records from ChangeMgmt domain.

    Args:
        modified_since: ISO-8601 timestamp for delta sync
        states:         e.g. ["RELEASED", "INWORK", "APPROVED"]
        max_records:    Safety cap

    Returns:
        List of change notice dicts matching mock_data/change_notices.json shape
    """
    params = {
        "$select": (
            "ID,Number,Name,State,Priority,Description,"
            "Reason,ModifyStamp"
        ),
        "$expand": (
            "AffectedItems($select=Number,Name),"
            "ResultingItems($select=Number,Name)"
        ),
        "$orderby": "ModifyStamp desc",
    }

    filters = []
    if modified_since:
        filters.append(f"ModifyStamp gt {modified_since}")
    if states:
        state_filter = " or ".join(f"State eq '{s}'" for s in states)
        filters.append(f"({state_filter})")

    if filters:
        params["$filter"] = " and ".join(filters)

    log.info(f"[CN] Fetching change notices with params: {params}")
    cns = client.get_all("ChangeMgmt/ChangeNotices", params=params, max_records=max_records)
    log.info(f"[CN] Fetched {len(cns)} change notices")
    return cns


def fetch_problem_reports(
    client: WindchillClient,
    modified_since: str = None,
    max_records: int = None,
) -> list[dict]:
    """Fetch ProblemReport (WTChangeIssue) records."""
    params = {
        "$select": "ID,Number,Name,State,Priority,Description,ModifyStamp",
        "$orderby": "ModifyStamp desc",
    }
    if modified_since:
        params["$filter"] = f"ModifyStamp gt {modified_since}"

    return client.get_all("ChangeMgmt/ProblemReports", params=params, max_records=max_records)


# ── Convenience: fetch everything for a full sync ─────────────────────────────

def fetch_all_for_indexing(
    client: WindchillClient,
    modified_since: str = None,
    max_per_type: int = 500,
    download_doc_content: bool = False,
) -> dict[str, list[dict]]:
    """
    Fetch all PLM object types in one call. Used by the sync script.

    Returns:
        {
          "parts":          [...],
          "documents":      [...],
          "boms":           [...],
          "change_notices": [...],
        }
    """
    log.info("=" * 60)
    log.info("Starting full Windchill data fetch")
    if modified_since:
        log.info(f"Delta sync — only objects modified after: {modified_since}")
    log.info("=" * 60)

    parts = fetch_parts(
        client,
        modified_since=modified_since,
        max_records=max_per_type,
    )

    boms = fetch_boms_for_assemblies(
        client,
        parts=parts,
        levels=3,
        max_assemblies=50,
    )

    documents = fetch_documents(
        client,
        modified_since=modified_since,
        max_records=max_per_type,
        download_content=download_doc_content,
    )

    change_notices = fetch_change_notices(
        client,
        modified_since=modified_since,
        max_records=max_per_type,
    )

    return {
        "parts": parts,
        "boms": boms,
        "documents": documents,
        "change_notices": change_notices,
    }
