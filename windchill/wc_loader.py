"""
Converts live Windchill API response dicts into indexable text chunks.

Mirrors the shape of backend/data/loader.py but for real Windchill data.
The real API field names differ slightly from the mock (e.g. nested objects,
different key casing) so we normalise here before passing to the indexer.
"""
import logging

log = logging.getLogger(__name__)


# ── Parts ─────────────────────────────────────────────────────────────────────

def part_to_chunk(part: dict) -> dict:
    """Convert a real WTPart OData response into an indexable chunk."""
    # Windchill returns nested TypeReference for Type — flatten it
    part_type = part.get("Type") or {}
    if isinstance(part_type, dict):
        part_type = part_type.get("Name", "N/A")

    text = (
        f"Part Number: {part.get('Number', 'N/A')}\n"
        f"Name: {part.get('Name', 'N/A')}\n"
        f"State: {part.get('State', 'N/A')}\n"
        f"Version: {part.get('Version', 'N/A')} Rev {part.get('Revision', 'N/A')}\n"
        f"Type: {part_type}\n"
        f"Description: {part.get('Description') or 'N/A'}\n"
        f"Last Modified: {part.get('ModifyStamp', 'N/A')}"
    )
    return {
        "id": part.get("ID", part.get("Number", "")),
        "type": "part",
        "number": part.get("Number", "N/A"),
        "name": part.get("Name", "N/A"),
        "state": part.get("State", "N/A"),
        "text": text,
    }


# ── Documents ─────────────────────────────────────────────────────────────────

def document_to_chunk(doc: dict) -> dict:
    """Convert a real WTDocument OData response into an indexable chunk."""
    primary = doc.get("PrimaryContent") or {}
    doc_type = doc.get("Type") or {}
    if isinstance(doc_type, dict):
        doc_type = doc_type.get("Name", "N/A")

    org = doc.get("Organization") or {}
    if isinstance(org, dict):
        org = org.get("Name", "N/A")

    text = (
        f"Document Number: {doc.get('Number', 'N/A')}\n"
        f"Name: {doc.get('Name', 'N/A')}\n"
        f"Type: {doc_type}\n"
        f"State: {doc.get('State', 'N/A')}\n"
        f"Version: {doc.get('Version', 'N/A')}\n"
        f"Organization: {org}\n"
        f"Description: {doc.get('Description') or 'N/A'}\n"
        f"File: {primary.get('FileName', 'N/A')}\n"
        f"Last Modified: {doc.get('ModifyStamp', 'N/A')}"
    )

    # Append extracted document text content if available
    text_content = primary.get("TextContent", "")
    if text_content:
        text += f"\n\n--- Document Content ---\n{text_content[:5000]}"

    return {
        "id": doc.get("ID", doc.get("Number", "")),
        "type": "document",
        "number": doc.get("Number", "N/A"),
        "name": doc.get("Name", "N/A"),
        "state": doc.get("State", "N/A"),
        "text": text,
    }


# ── BOM ───────────────────────────────────────────────────────────────────────

def _flatten_bom_components(components: list, level: int = 0) -> list[str]:
    lines = []
    indent = "  " * level
    for comp in components:
        part = comp.get("Part") or {}
        use = comp.get("PartUse") or {}
        lines.append(
            f"{indent}├─ [{use.get('FindNumber', '?')}] "
            f"{part.get('Number', '?')} | {part.get('Name', '?')} | "
            f"Qty: {use.get('Quantity', '?')} {use.get('Unit', 'EA')} | "
            f"State: {part.get('State', '?')}"
        )
        if comp.get("Components"):
            lines.extend(_flatten_bom_components(comp["Components"], level + 1))
    return lines


def bom_to_chunk(bom: dict) -> dict:
    """Convert a real BOM tree response into an indexable chunk."""
    parent = bom.get("ParentPart", {})
    bom_lines = _flatten_bom_components(bom.get("Components", []))
    bom_text = "\n".join(bom_lines) if bom_lines else "  (no child components)"

    text = (
        f"Bill of Materials for: {parent.get('Number', 'N/A')} - {parent.get('Name', 'N/A')}\n"
        f"Parent State: {parent.get('State', 'N/A')}\n\n"
        f"Structure:\n{bom_text}"
    )
    return {
        "id": f"BOM-{parent.get('ID', parent.get('Number', 'unknown'))}",
        "type": "bom",
        "number": parent.get("Number", "N/A"),
        "name": f"BOM of {parent.get('Name', 'N/A')}",
        "state": parent.get("State", "N/A"),
        "text": text,
    }


# ── Change Notices ────────────────────────────────────────────────────────────

def change_notice_to_chunk(cn: dict) -> dict:
    """Convert a real ChangeNotice OData response into an indexable chunk."""
    # AffectedItems — real Windchill returns these as AffectedItems navigation
    affected = cn.get("AffectedItems") or []
    affected_text = "\n".join(
        f"  - {item.get('Number', '?')} ({item.get('Name', '?')})"
        for item in affected
    ) or "  None listed"

    text = (
        f"Change Notice: {cn.get('Number', 'N/A')}\n"
        f"Title / Name: {cn.get('Name', 'N/A')}\n"
        f"State: {cn.get('State', 'N/A')}\n"
        f"Priority: {cn.get('Priority', 'N/A')}\n"
        f"Description: {cn.get('Description') or 'N/A'}\n"
        f"Reason: {cn.get('Reason') or 'N/A'}\n"
        f"Last Modified: {cn.get('ModifyStamp', 'N/A')}\n"
        f"Affected Parts / Items:\n{affected_text}"
    )
    return {
        "id": cn.get("ID", cn.get("Number", "")),
        "type": "change_notice",
        "number": cn.get("Number", "N/A"),
        "name": cn.get("Name", "N/A"),
        "state": cn.get("State", "N/A"),
        "text": text,
    }


# ── All-in-one converter ──────────────────────────────────────────────────────

def convert_all_to_chunks(data: dict) -> list[dict]:
    """
    Convert the dict returned by windchill.fetcher.fetch_all_for_indexing()
    into a flat list of indexable text chunks.

    Args:
        data: {"parts": [...], "documents": [...], "boms": [...], "change_notices": [...]}

    Returns:
        List of chunk dicts ready for search/indexer.py
    """
    chunks: list[dict] = []

    for part in data.get("parts", []):
        try:
            chunks.append(part_to_chunk(part))
        except Exception as e:
            log.warning(f"Skipping part {part.get('Number')}: {e}")

    for doc in data.get("documents", []):
        try:
            chunks.append(document_to_chunk(doc))
        except Exception as e:
            log.warning(f"Skipping doc {doc.get('Number')}: {e}")

    for bom in data.get("boms", []):
        try:
            chunks.append(bom_to_chunk(bom))
        except Exception as e:
            log.warning(f"Skipping BOM {bom.get('ParentPart', {}).get('Number')}: {e}")

    for cn in data.get("change_notices", []):
        try:
            chunks.append(change_notice_to_chunk(cn))
        except Exception as e:
            log.warning(f"Skipping CN {cn.get('Number')}: {e}")

    log.info(f"[Converter] Converted {len(chunks)} total chunks")
    return chunks
