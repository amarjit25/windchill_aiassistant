"""
Windchill OData Mock Server

A FastAPI application that mimics the PTC Windchill REST OData API exactly,
serving the sample mock_data/*.json files through the same URL structure
as a real Windchill server.

Your windchill/client.py connects to this instead of a real server —
zero code changes needed.

Run with:
    uvicorn mock_server.windchill_mock:app --port 9090

Then set in .env:
    WC_BASE_URL=http://localhost:9090
    WC_USERNAME=demo
    WC_PASSWORD=demo
    WC_SSL_VERIFY=false
"""
import json
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import JSONResponse
import secrets

app = FastAPI(
    title="Windchill OData Mock Server",
    description="Mimics the PTC Windchill REST OData API for development and testing",
    version="1.0.0",
)

security = HTTPBasic()
MOCK_DATA = Path(__file__).parent.parent / "mock_data"

# ── Simple Basic Auth (accepts any user / demo:demo) ─────────────────────────

def check_auth(credentials: HTTPBasicCredentials = Depends(security)):
    """Accept demo:demo or any credentials for testing."""
    if not (
        secrets.compare_digest(credentials.username, "demo") and
        secrets.compare_digest(credentials.password, "demo")
    ):
        # In a permissive mock, accept anything — comment this block to lock down
        pass
    return credentials.username


# ── Helper ───────────────────────────────────────────────────────────────────

def load_mock(filename: str) -> dict:
    with open(MOCK_DATA / filename, "r") as f:
        return json.load(f)


def odata_response(value: list, entity_type: str = "") -> dict:
    """Wrap a list in the standard OData response envelope."""
    return {
        "@odata.context": f"http://localhost:9090/Windchill/servlet/odata/$metadata#{entity_type}",
        "value": value,
    }


def filter_by_state(records: list, state: str | None) -> list:
    if not state:
        return records
    return [r for r in records if r.get("State", "").upper() == state.upper()]


def filter_modified_since(records: list, since: str | None) -> list:
    if not since:
        return records
    return [r for r in records if r.get("ModifyStamp", "") >= since]


def paginate(records: list, top: int, skip: int) -> tuple[list, bool]:
    """Return page slice and whether there are more records."""
    total = len(records)
    page = records[skip : skip + top]
    has_more = (skip + top) < total
    return page, has_more


# ── Metadata endpoints ────────────────────────────────────────────────────────

@app.get("/Windchill/servlet/odata/{domain}/$metadata")
def domain_metadata(domain: str, user: str = Depends(check_auth)):
    """Returns a minimal OData metadata document for the domain."""
    return JSONResponse(
        content={
            "@odata.context": f"http://localhost:9090/Windchill/servlet/odata/{domain}/$metadata",
            "version": "4.0",
            "domain": domain,
            "status": "mock server running",
        }
    )


@app.get("/Windchill/servlet/odata/$metadata")
def root_metadata(user: str = Depends(check_auth)):
    return {"status": "Windchill Mock OData Server v1.0", "domains": ["ProdMgmt", "DocMgmt", "ChangeMgmt"]}


# ── ProdMgmt — Parts ──────────────────────────────────────────────────────────

@app.get("/Windchill/servlet/odata/ProdMgmt/Parts")
def get_parts(
    request: Request,
    user: str = Depends(check_auth),
):
    """GET /ProdMgmt/Parts — returns all parts with optional OData filters."""
    params = dict(request.query_params)
    top = int(params.get("$top", 100))
    skip = int(params.get("$skip", 0))
    filter_expr = params.get("$filter", "")

    data = load_mock("parts.json")
    records = data.get("value", [])

    # Basic $filter support for State and ModifyStamp
    if "State eq" in filter_expr:
        for state in ["RELEASED", "INWORK", "OBSOLETE"]:
            if f"State eq '{state}'" in filter_expr:
                records = [r for r in records if r.get("State") == state]

    if "ModifyStamp gt" in filter_expr:
        since = filter_expr.split("ModifyStamp gt")[-1].strip().strip("'")
        records = filter_modified_since(records, since)

    page, has_more = paginate(records, top, skip)
    response = odata_response(page, "Parts")

    if has_more:
        next_skip = skip + top
        response["@odata.nextLink"] = (
            f"http://localhost:9090/Windchill/servlet/odata/ProdMgmt/Parts"
            f"?$top={top}&$skip={next_skip}"
        )
    return response


@app.get("/Windchill/servlet/odata/ProdMgmt/Parts('{part_id}')")
def get_part_by_id(part_id: str, user: str = Depends(check_auth)):
    """GET /ProdMgmt/Parts('{id}') — returns a single part."""
    data = load_mock("parts.json")
    for part in data.get("value", []):
        if part.get("ID") == part_id or part.get("Number") == part_id:
            return part
    raise HTTPException(status_code=404, detail=f"Part '{part_id}' not found")


# ── ProdMgmt — BOM ────────────────────────────────────────────────────────────

@app.post("/Windchill/servlet/odata/ProdMgmt/Parts('{part_id}')/PTC.ProdMgmt.GetBOM")
@app.get("/Windchill/servlet/odata/ProdMgmt/Parts('{part_id}')/PTC.ProdMgmt.GetBOM")
def get_bom(part_id: str, user: str = Depends(check_auth)):
    """GET/POST /ProdMgmt/Parts('{id}')/PTC.ProdMgmt.GetBOM — returns BOM tree."""
    data = load_mock("bom.json")
    for bom in data.get("BOMs", []):
        parent = bom.get("ParentPart", {})
        if parent.get("ID") == part_id or parent.get("Number") in part_id:
            return {
                **bom["ParentPart"],
                "Components": bom.get("Components", []),
            }
    # Return empty BOM if no match
    return {"ID": part_id, "Components": []}


# ── DocMgmt — Documents ───────────────────────────────────────────────────────

@app.get("/Windchill/servlet/odata/DocMgmt/Documents")
def get_documents(
    request: Request,
    user: str = Depends(check_auth),
):
    """GET /DocMgmt/Documents — returns all documents."""
    params = dict(request.query_params)
    top = int(params.get("$top", 100))
    skip = int(params.get("$skip", 0))
    filter_expr = params.get("$filter", "")

    data = load_mock("documents.json")
    records = data.get("value", [])

    if "State eq" in filter_expr:
        for state in ["RELEASED", "INWORK", "OBSOLETE"]:
            if f"State eq '{state}'" in filter_expr:
                records = [r for r in records if r.get("State") == state]

    if "ModifyStamp gt" in filter_expr:
        since = filter_expr.split("ModifyStamp gt")[-1].strip().strip("'")
        records = filter_modified_since(records, since)

    page, has_more = paginate(records, top, skip)
    response = odata_response(page, "Documents")

    if has_more:
        next_skip = skip + top
        response["@odata.nextLink"] = (
            f"http://localhost:9090/Windchill/servlet/odata/DocMgmt/Documents"
            f"?$top={top}&$skip={next_skip}"
        )
    return response


@app.get("/Windchill/servlet/odata/DocMgmt/Documents('{doc_id}')")
def get_document_by_id(doc_id: str, user: str = Depends(check_auth)):
    data = load_mock("documents.json")
    for doc in data.get("value", []):
        if doc.get("ID") == doc_id or doc.get("Number") == doc_id:
            return doc
    raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")


@app.get("/Windchill/servlet/odata/DocMgmt/Documents('{doc_id}')/PrimaryContent/PTC.ApplicationData/Content/URL")
def get_document_content_url(doc_id: str, user: str = Depends(check_auth)):
    """Returns a fake content download URL for the document."""
    data = load_mock("documents.json")
    for doc in data.get("value", []):
        if doc.get("ID") == doc_id or doc.get("Number") == doc_id:
            primary = doc.get("PrimaryContent", {})
            filename = primary.get("FileName", "document.pdf")
            return {
                "@odata.context": "http://localhost:9090/Windchill/servlet/odata/$metadata#ContentItems/Content/URL",
                "value": f"http://localhost:9090/mock-content/{doc_id}/{filename}",
            }
    raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")


@app.get("/mock-content/{doc_id}/{filename}")
def download_document_content(doc_id: str, filename: str, user: str = Depends(check_auth)):
    """Serves mock document content as plain text (simulating a PDF download)."""
    data = load_mock("documents.json")
    for doc in data.get("value", []):
        if doc.get("ID") == doc_id or doc.get("Number") == doc_id:
            primary = doc.get("PrimaryContent", {})
            text = primary.get("TextContent", f"Mock content for {doc.get('Name', 'document')}")
            # Return as plain text (in reality this would be a PDF binary)
            return JSONResponse(
                content={"text": text},
                headers={"Content-Type": "application/json"},
            )
    raise HTTPException(status_code=404)


# ── ChangeMgmt — Change Notices ───────────────────────────────────────────────

@app.get("/Windchill/servlet/odata/ChangeMgmt/ChangeNotices")
def get_change_notices(
    request: Request,
    user: str = Depends(check_auth),
):
    """GET /ChangeMgmt/ChangeNotices — returns all change notices."""
    params = dict(request.query_params)
    top = int(params.get("$top", 100))
    skip = int(params.get("$skip", 0))
    filter_expr = params.get("$filter", "")

    data = load_mock("change_notices.json")
    records = data.get("value", [])

    if "State eq" in filter_expr:
        for state in ["RELEASED", "INWORK", "APPROVED"]:
            if f"State eq '{state}'" in filter_expr:
                records = [r for r in records if r.get("State") == state]

    if "ModifyStamp gt" in filter_expr:
        since = filter_expr.split("ModifyStamp gt")[-1].strip().strip("'")
        records = filter_modified_since(records, since)

    page, _ = paginate(records, top, skip)
    return odata_response(page, "ChangeNotices")


@app.get("/Windchill/servlet/odata/ChangeMgmt/ChangeNotices('{cn_id}')")
def get_change_notice_by_id(cn_id: str, user: str = Depends(check_auth)):
    data = load_mock("change_notices.json")
    for cn in data.get("value", []):
        if cn.get("ID") == cn_id or cn.get("Number") == cn_id:
            return cn
    raise HTTPException(status_code=404, detail=f"Change Notice '{cn_id}' not found")


@app.get("/Windchill/servlet/odata/ChangeMgmt/ProblemReports")
def get_problem_reports(user: str = Depends(check_auth)):
    """Returns an empty list (no mock problem reports in sample data)."""
    return odata_response([], "ProblemReports")


# ── Root info ─────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "message": "Windchill OData Mock Server",
        "endpoints": {
            "parts":          "GET /Windchill/servlet/odata/ProdMgmt/Parts",
            "bom":            "GET /Windchill/servlet/odata/ProdMgmt/Parts('{id}')/PTC.ProdMgmt.GetBOM",
            "documents":      "GET /Windchill/servlet/odata/DocMgmt/Documents",
            "change_notices": "GET /Windchill/servlet/odata/ChangeMgmt/ChangeNotices",
        },
        "auth": "Basic auth — use demo:demo",
        "docs": "http://localhost:9090/docs",
    }
