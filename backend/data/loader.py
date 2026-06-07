"""
Data loader — converts PLM records into flat text chunks for embedding.

Source is selected by USE_MOCK_DATA in .env:
  true  → reads from mock_data/ JSON files
  false → fetches live data from Windchill REST API
"""
import json
from pathlib import Path
from typing import Any

from backend import config


# ─────────────────────────────────────────────────────────────────────────────
# Raw loaders — mock (JSON files) and live (Windchill REST API)
# ─────────────────────────────────────────────────────────────────────────────

def _load_json(filename: str) -> dict:
    path = config.MOCK_DATA_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_parts() -> list[dict]:
    if config.USE_MOCK_DATA:
        return _load_json("parts.json").get("value", [])
    from backend.data.windchill_client import fetch_parts
    return fetch_parts()


def load_documents() -> list[dict]:
    if config.USE_MOCK_DATA:
        return _load_json("documents.json").get("value", [])
    from backend.data.windchill_client import fetch_documents
    return fetch_documents()


def load_bom() -> list[dict]:
    if config.USE_MOCK_DATA:
        return _load_json("bom.json").get("BOMs", [])
    # For live data: fetch BOM for every part that has one
    from backend.data.windchill_client import fetch_bom
    parts = load_parts()
    boms = []
    for part in parts:
        bom = fetch_bom(
            part_id=part["ID"],
            part_number=part["Number"],
            part_name=part["Name"],
            part_state=part["State"],
        )
        if bom:
            boms.append(bom)
    return boms


def load_change_notices() -> list[dict]:
    if config.USE_MOCK_DATA:
        return _load_json("change_notices.json").get("value", [])
    from backend.data.windchill_client import fetch_change_notices
    return fetch_change_notices()


# ─────────────────────────────────────────────────────────────────────────────
# Text conversion — one text blob + metadata per PLM object
# ─────────────────────────────────────────────────────────────────────────────

def part_to_chunk(part: dict) -> dict:
    """Convert a WTPart record into a searchable text chunk + metadata."""
    text = (
        f"Part Number: {part['Number']}\n"
        f"Name: {part['Name']}\n"
        f"State: {part['State']}\n"
        f"Version: {part.get('Version', 'N/A')} Rev {part.get('Revision', 'N/A')}\n"
        f"Type: {part.get('Type', 'N/A')}\n"
        f"Material: {part.get('Material', 'N/A')}\n"
        f"Weight (kg): {part.get('Weight_kg', 'N/A')}\n"
        f"Organization: {part.get('Organization', 'N/A')}\n"
        f"Description: {part.get('Description', 'N/A')}\n"
        f"Last Modified: {part.get('ModifyStamp', 'N/A')}"
    )
    return {
        "id": part["ID"],
        "type": "part",
        "number": part["Number"],
        "name": part["Name"],
        "state": part["State"],
        "text": text,
    }


def document_to_chunk(doc: dict) -> dict:
    """Convert a WTDocument record into a searchable text chunk + metadata."""
    primary = doc.get("PrimaryContent", {})
    text = (
        f"Document Number: {doc['Number']}\n"
        f"Name: {doc['Name']}\n"
        f"Type: {doc.get('Type', 'N/A')}\n"
        f"State: {doc['State']}\n"
        f"Version: {doc.get('Version', 'N/A')}\n"
        f"Author: {doc.get('Author', 'N/A')}\n"
        f"Organization: {doc.get('Organization', 'N/A')}\n"
        f"Description: {doc.get('Description', 'N/A')}\n"
        f"File: {primary.get('FileName', 'N/A')} ({primary.get('FileSize_kb', 'N/A')} KB)\n"
        f"Last Modified: {doc.get('ModifyStamp', 'N/A')}\n\n"
        f"--- Document Content ---\n"
        f"{primary.get('TextContent', '')}"
    )
    return {
        "id": doc["ID"],
        "type": "document",
        "number": doc["Number"],
        "name": doc["Name"],
        "state": doc["State"],
        "text": text,
    }


def _flatten_bom(parent_number: str, parent_name: str, components: list, level: int = 0) -> list[str]:
    """Recursively flatten BOM tree into readable lines."""
    lines = []
    indent = "  " * level
    for comp in components:
        part = comp.get("Part", {})
        use = comp.get("PartUse", {})
        lines.append(
            f"{indent}├─ [{use.get('FindNumber', '?')}] "
            f"{part.get('Number', '?')} | {part.get('Name', '?')} | "
            f"Qty: {use.get('Quantity', '?')} {use.get('Unit', 'EA')} | "
            f"State: {part.get('State', '?')}"
        )
        if comp.get("Components"):
            lines.extend(_flatten_bom(part.get("Number", ""), part.get("Name", ""), comp["Components"], level + 1))
    return lines


def bom_to_chunk(bom: dict) -> dict:
    """Convert a BOM tree into a searchable text chunk + metadata."""
    parent = bom.get("ParentPart", {})
    bom_lines = _flatten_bom(parent.get("Number", ""), parent.get("Name", ""), bom.get("Components", []))
    bom_text = "\n".join(bom_lines)
    text = (
        f"Bill of Materials for: {parent.get('Number', 'N/A')} - {parent.get('Name', 'N/A')}\n"
        f"Parent State: {parent.get('State', 'N/A')}\n\n"
        f"Structure:\n{bom_text}"
    )
    return {
        "id": f"BOM-{parent.get('ID', 'unknown')}",
        "type": "bom",
        "number": parent.get("Number", "N/A"),
        "name": f"BOM of {parent.get('Name', 'N/A')}",
        "state": parent.get("State", "N/A"),
        "text": text,
    }


def change_notice_to_chunk(cn: dict) -> dict:
    """Convert a ChangeNotice record into a searchable text chunk + metadata."""
    affected_parts = "\n".join(
        f"  - {p['PartNumber']} ({p['PartName']}): {p.get('Action', 'N/A')} — {p.get('Disposition', '')}"
        for p in cn.get("AffectedParts", [])
    )
    affected_docs = "\n".join(
        f"  - {d['DocNumber']} ({d['DocName']})"
        for d in cn.get("AffectedDocuments", [])
    )
    text = (
        f"Change Notice: {cn['Number']}\n"
        f"Title: {cn['Title']}\n"
        f"State: {cn['State']}\n"
        f"Priority: {cn.get('Priority', 'N/A')}\n"
        f"Category: {cn.get('Category', 'N/A')}\n"
        f"Description: {cn.get('Description', 'N/A')}\n"
        f"Reason: {cn.get('Reason', 'N/A')}\n"
        f"Initiated By: {cn.get('InitiatedBy', 'N/A')}\n"
        f"Release Date: {cn.get('ReleaseDate', 'Not yet released')}\n"
        f"Effectivity Date: {cn.get('EffectivityDate', 'Not yet effective')}\n"
        f"Affected Parts:\n{affected_parts or '  None'}\n"
        f"Affected Documents:\n{affected_docs or '  None'}"
    )
    return {
        "id": cn["ID"],
        "type": "change_notice",
        "number": cn["Number"],
        "name": cn["Title"],
        "state": cn["State"],
        "text": text,
    }


# ─────────────────────────────────────────────────────────────────────────────
# All-in-one loader
# ─────────────────────────────────────────────────────────────────────────────

def load_all_chunks() -> list[dict]:
    """Load and convert all mock data sources into indexable chunks."""
    chunks: list[dict] = []

    for part in load_parts():
        chunks.append(part_to_chunk(part))

    for doc in load_documents():
        chunks.append(document_to_chunk(doc))

    for bom in load_bom():
        chunks.append(bom_to_chunk(bom))

    for cn in load_change_notices():
        chunks.append(change_notice_to_chunk(cn))

    print(f"[Loader] Loaded {len(chunks)} chunks from mock data")
    return chunks
