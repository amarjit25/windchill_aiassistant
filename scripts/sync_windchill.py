"""
Sync real Windchill data into the Qdrant vector DB.

Supports two modes:
  --full     Drop collection and reindex everything from scratch
  --delta    Only fetch objects modified since the last sync (fast, incremental)

Usage:
    python scripts/sync_windchill.py --full
    python scripts/sync_windchill.py --delta
    python scripts/sync_windchill.py --delta --since 2024-11-01T00:00:00Z
    python scripts/sync_windchill.py --test-connection
"""
import sys
import json
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

LAST_SYNC_FILE = Path(__file__).parent.parent / ".last_sync_timestamp"


def load_last_sync() -> str | None:
    """Read the timestamp of the last successful sync."""
    if LAST_SYNC_FILE.exists():
        return LAST_SYNC_FILE.read_text().strip()
    return None


def save_last_sync(ts: str) -> None:
    """Persist the current sync timestamp for next delta run."""
    LAST_SYNC_FILE.write_text(ts)
    log.info(f"Last sync timestamp saved: {ts}")


def test_connection():
    """Verify Windchill connectivity and print collection counts."""
    from windchill.client import WindchillClient
    from backend import config

    print("\n── Windchill Connection Test ──")
    print(f"  URL:      {config.WC_BASE_URL}")
    print(f"  Username: {config.WC_USERNAME}")
    print(f"  SSL:      {'VERIFY' if config.WC_SSL_VERIFY else 'SKIP (insecure)'}")

    with WindchillClient() as client:
        # Test each domain metadata endpoint
        for domain in ["ProdMgmt", "DocMgmt", "ChangeMgmt"]:
            try:
                resp = client._get(f"{domain}/$metadata")
                print(f"  ✅  {domain} domain — reachable")
            except Exception as e:
                print(f"  ❌  {domain} domain — {e}")

        # Test a small data fetch
        print("\n── Sample data fetch (top 3 parts) ──")
        try:
            parts = client.get_all(
                "ProdMgmt/Parts",
                params={"$top": 3, "$select": "Number,Name,State"},
                max_records=3,
            )
            for p in parts:
                print(f"  🔩  {p.get('Number')} | {p.get('Name')} | {p.get('State')}")
        except Exception as e:
            print(f"  ❌  Parts fetch failed: {e}")

    print()


def run_sync(
    mode: str,
    modified_since: str = None,
    max_per_type: int = 1000,
    download_doc_content: bool = False,
    recreate_collection: bool = False,
):
    from windchill.client import WindchillClient
    from windchill.fetcher import fetch_all_for_indexing
    from windchill.wc_loader import convert_all_to_chunks
    from backend.search.indexer import create_collection, index_chunks, collection_info

    sync_start = datetime.now(timezone.utc).isoformat()

    print("\n══════════════════════════════════════════════════")
    print(f"  Windchill PLM AI Assistant — {mode.upper()} SYNC")
    print("══════════════════════════════════════════════════\n")

    # Determine delta timestamp
    if mode == "delta":
        if not modified_since:
            modified_since = load_last_sync()
        if modified_since:
            print(f"📅  Delta sync — only objects modified after: {modified_since}")
        else:
            print("⚠️   No previous sync found — falling back to full sync")
            mode = "full"

    # Prepare collection
    create_collection(recreate=(mode == "full" or recreate_collection))

    # Fetch from Windchill
    print("\n🌐  Connecting to Windchill and fetching data...\n")
    with WindchillClient() as client:
        raw_data = fetch_all_for_indexing(
            client=client,
            modified_since=modified_since if mode == "delta" else None,
            max_per_type=max_per_type,
            download_doc_content=download_doc_content,
        )

    # Summary
    print(f"\n📊  Fetched from Windchill:")
    print(f"    Parts:           {len(raw_data['parts'])}")
    print(f"    Documents:       {len(raw_data['documents'])}")
    print(f"    BOMs:            {len(raw_data['boms'])}")
    print(f"    Change Notices:  {len(raw_data['change_notices'])}")

    # Convert to chunks
    chunks = convert_all_to_chunks(raw_data)
    print(f"\n🔤  Converted to {len(chunks)} text chunks for embedding\n")

    if not chunks:
        print("⚠️   No chunks to index. Check your Windchill connection and filters.")
        return

    # Embed + index
    total = index_chunks(chunks)

    # Persist sync timestamp
    save_last_sync(sync_start)

    # Final report
    info = collection_info()
    print(f"\n✅  {mode.upper()} SYNC COMPLETE")
    print(f"   Chunks indexed this run:  {total}")
    print(f"   Total points in Qdrant:   {info['points_count']}")
    print(f"   Sync timestamp saved:     {sync_start}")
    print(f"\n   Start the API:  uvicorn backend.main:app --reload --port 8000")
    print(f"   Test it:        python test_queries.py\n")


# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sync Windchill PLM data into the AI Assistant vector DB"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full",            action="store_true", help="Full reindex (drops existing data)")
    group.add_argument("--delta",           action="store_true", help="Incremental sync (only changed objects)")
    group.add_argument("--test-connection", action="store_true", help="Test Windchill connectivity only")

    parser.add_argument("--since",          type=str,  default=None,  help="Override delta timestamp (ISO-8601)")
    parser.add_argument("--max",            type=int,  default=1000,  help="Max records per object type (default 1000)")
    parser.add_argument("--download-docs",  action="store_true",      help="Download and embed PDF content")
    parser.add_argument("--recreate",       action="store_true",      help="Force drop+recreate collection")

    args = parser.parse_args()

    if args.test_connection:
        test_connection()
    elif args.full:
        run_sync("full", max_per_type=args.max, download_doc_content=args.download_docs, recreate_collection=True)
    elif args.delta:
        run_sync("delta", modified_since=args.since, max_per_type=args.max, download_doc_content=args.download_docs)


if __name__ == "__main__":
    main()
