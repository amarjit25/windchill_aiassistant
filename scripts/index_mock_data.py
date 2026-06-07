"""
One-shot script to index all mock Windchill data into Qdrant.

Run from the project root:
    python scripts/index_mock_data.py

Options:
    --recreate   Drop and recreate the collection before indexing
    --info       Only show collection info (no indexing)
"""
import sys
import argparse

# Ensure project root is in path when running as a script
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from backend.data.loader import load_all_chunks
from backend.search.indexer import create_collection, index_chunks, collection_info


def main():
    parser = argparse.ArgumentParser(description="Index Windchill mock data into Qdrant")
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate the collection")
    parser.add_argument("--info", action="store_true", help="Print collection info and exit")
    args = parser.parse_args()

    if args.info:
        try:
            info = collection_info()
            print("\n── Qdrant Collection Info ──")
            for k, v in info.items():
                print(f"  {k}: {v}")
        except Exception as e:
            print(f"Error: {e}")
            print("Is Qdrant running? Start it with: docker-compose up -d qdrant")
        return

    print("\n══════════════════════════════════════════════")
    print("  Windchill PLM AI Assistant — Data Indexing")
    print("══════════════════════════════════════════════\n")

    # 1. Create (or recreate) the Qdrant collection
    create_collection(recreate=args.recreate)

    # 2. Load all mock data as text chunks
    chunks = load_all_chunks()

    # 3. Embed + upsert into Qdrant
    print(f"\n[Index] Indexing {len(chunks)} chunks...")
    total = index_chunks(chunks)

    # 4. Confirm
    print(f"\n✅ Done! {total} PLM objects indexed.")
    info = collection_info()
    print(f"   Collection: {info['name']}")
    print(f"   Total points in DB: {info['points_count']}")
    print(f"\nNext step: start the API server")
    print("   uvicorn backend.main:app --reload --port 8000")
    print("   Then open: http://localhost:8000/docs\n")


if __name__ == "__main__":
    main()
