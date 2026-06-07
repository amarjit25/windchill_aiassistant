"""
POC Test Script — runs a set of natural language queries against the
Windchill PLM AI Assistant API and prints the results.

Run from the project root:
    python test_queries.py
"""
import requests
import json
import time

BASE = "http://localhost:8000/api/v1"


def divider(char="=", width=70):
    print(char * width)


def ask(query: str, filter_type: str = None, filter_state: str = None, top_k: int = 6):
    payload = {"query": query, "top_k": top_k}
    if filter_type:
        payload["filter_type"] = filter_type
    if filter_state:
        payload["filter_state"] = filter_state

    try:
        resp = requests.post(f"{BASE}/ask", json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.ConnectionError:
        print("❌  Cannot connect to API. Is the server running?")
        print("    Start it with: uvicorn backend.main:app --reload --port 8000")
        return
    except Exception as e:
        print(f"❌  Error: {e}")
        return

    divider("=")
    print(f"🔍  QUERY: {query}")
    if filter_type:
        print(f"    filter_type={filter_type}", end="")
    if filter_state:
        print(f"  filter_state={filter_state}", end="")
    if filter_type or filter_state:
        print()
    divider("-")

    print("\n📝  ANSWER:\n")
    print(data.get("answer", "No answer returned."))

    print("\n📎  SOURCES USED:")
    sources = data.get("sources", [])
    if sources:
        for s in sources:
            icon = {"part": "🔩", "document": "📄", "bom": "🌲", "change_notice": "🔔"}.get(s["type"], "•")
            state_flag = "⚠️ " if s["state"] in ("INWORK", "OBSOLETE") else ""
            print(f"  {icon} [{s['type'].upper()}] {s['number']} — {s['name']}  "
                  f"State: {state_flag}{s['state']}  "
                  f"(score: {s['relevance_score']})")
    else:
        print("  None")

    usage = data.get("usage", {})
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_icon = "✅" if cache_read > 0 else "🔄"
    print(f"\n📊  TOKEN USAGE:")
    print(f"  Input:          {usage.get('input_tokens', 0):>6}")
    print(f"  Output:         {usage.get('output_tokens', 0):>6}")
    print(f"  Cache created:  {usage.get('cache_creation_input_tokens', 0):>6}")
    print(f"  Cache read:     {cache_read:>6}  {cache_icon} {'(prompt cached — cheaper!)' if cache_read > 0 else '(first call — cache being created)'}")
    print(f"  Model:          {data.get('model', 'N/A')}")
    print()
    time.sleep(0.5)   # small pause between calls to be polite to the API


def health_check():
    divider("=")
    print("🩺  HEALTH CHECK")
    divider("-")
    try:
        resp = requests.get(f"{BASE}/health", timeout=10)
        data = resp.json()
        status = data.get("status", "unknown")
        coll = data.get("collection") or {}
        if status == "ok":
            print(f"  ✅  API status: {status}")
            print(f"  📦  Collection: {coll.get('name')}  |  "
                  f"Points: {coll.get('points_count')}  |  "
                  f"Vectors: {coll.get('vectors_count')}")
        else:
            print(f"  ⚠️   API status: {status}")
            print("  Make sure Qdrant is running: docker-compose up -d qdrant")
            print("  And data is indexed: python scripts/index_mock_data.py")
        return status == "ok"
    except Exception as e:
        print(f"  ❌  Cannot reach API: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Main test suite
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n")
    divider("═")
    print("  🚀  Windchill PLM AI Assistant — POC Test Suite")
    divider("═")

    # 0. Health check before proceeding
    ok = health_check()
    if not ok:
        exit(1)

    print("\n")
    divider("═")
    print("  TEST GROUP 1 — Parts Lookup")
    divider("═")
    print()

    ask("What material is the Main Engine Frame made of and what is its weight?")

    ask("What is the operating speed range of the drive shaft assembly?")

    ask("List all parts that are currently INWORK and explain why they matter.")

    ask("Is part ENG-NACELLE-010 still approved for new production?")

    print("\n")
    divider("═")
    print("  TEST GROUP 2 — Documents & Specifications")
    divider("═")
    print()

    ask("What are the engine thrust and specific fuel consumption targets?")

    ask("What is the oil filter replacement interval and what part number is needed?")

    ask("What chemical composition is required for the titanium alloy Ti-6Al-4V?")

    ask("What DO-178C assurance level is the FADEC certified to and why?")

    print("\n")
    divider("═")
    print("  TEST GROUP 3 — Change Notices")
    divider("═")
    print()

    ask("What change notices are currently active and what do they change?")

    ask("Which parts are affected by CN-2024-0047 and what action is required?")

    ask("Are there any safety-critical change notices? What parts are involved?")

    print("\n")
    divider("═")
    print("  TEST GROUP 4 — BOM Structure")
    divider("═")
    print()

    ask("What is the complete BOM structure under the Main Engine Frame?")

    ask("How many compressor fan blades are used in the engine assembly and what is their state?")

    print("\n")
    divider("═")
    print("  TEST GROUP 5 — Cross-Domain Reasoning (hardest)")
    divider("═")
    print()

    ask("What was the root cause of the bearing failure and what change was made to fix it?")

    ask("Summarize all known issues and open actions in the current PLM system.")

    divider("═")
    print("  ✅  Test suite complete!")
    divider("═")
    print()
