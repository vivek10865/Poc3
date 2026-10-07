"""
POC-003  Mock Dynamics 365 Events API

A local FastAPI service that imitates the shape of the Dynamics 365 Web API (OData v4)
for IRONMAN events, athletes, customers and cases, using deterministic synthetic data
(events/athletes come from POC-001; customers/cases are generated with a fixed seed).

Run:  uvicorn app:app --reload --port 8100      Docs: http://localhost:8100/docs
"""
import csv
import logging
import os
import random
import re
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

load_dotenv()

# ---------------------------------------------------------------- config (env only)
ENV = os.getenv("MOCK_ENV", "local")
AUTH_ENABLED = os.getenv("MOCK_AUTH_ENABLED", "true").lower() == "true"
TOKEN = os.getenv("MOCK_TOKEN", "dev-token-change-me")
DEFAULT_PAGE = int(os.getenv("MOCK_DEFAULT_PAGE_SIZE", "50"))
MAX_PAGE = int(os.getenv("MOCK_MAX_PAGE_SIZE", "200"))
logging.basicConfig(level=os.getenv("MOCK_LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mock-d365")

API_BASE = "/api/data/v9.2"
DATA_DIR = Path(__file__).parent / "data"
SEED = 42
REFERENCE_DATE = datetime(2026, 9, 1)
NS = uuid.UUID("6f1d2a3c-0000-4000-8000-00000000d365")


def gid(kind: str, key: Any) -> str:
    """Deterministic GUID: same input -> same id on every run and every machine."""
    return str(uuid.uuid5(NS, f"{kind}:{key}"))


# ---------------------------------------------------------------- synthetic data
def _csv(name):
    with open(DATA_DIR / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_data() -> dict[str, list[dict]]:
    rnd = random.Random(SEED)
    locs = {r["location_id"]: r for r in _csv("locations.csv")}

    events = []
    for e in _csv("events.csv"):
        loc = locs[e["location_id"]]
        events.append({
            "ironman_eventid": gid("event", e["event_id"]),
            "ironman_name": e["event_name"],
            "ironman_eventtype": e["event_type"],
            "ironman_eventdate": e["event_date"],
            "ironman_city": loc["city"],
            "ironman_country": loc["country"],
            "ironman_region": loc["region"],
            "ironman_capacity": int(e["capacity"]),
            "ironman_registrationopen": e["registration_open_date"],
            "ironman_registrationclose": e["registration_close_date"],
            "statuscode": e["status"],
        })

    athletes = []
    for a in _csv("athletes.csv"):
        athletes.append({
            "contactid": gid("athlete", a["athlete_id"]),
            "ironman_athleteno": int(a["athlete_id"]),
            "firstname": a["first_name"],
            "lastname": a["last_name"],
            "fullname": f'{a["first_name"]} {a["last_name"]}',
            "emailaddress1": a["email"],
            "gendercode": a["gender"],
            "birthdate": a["birth_date"],
            "ironman_agegroup": a["age_group"],
            "address1_country": a["nationality"],
            "ironman_ispro": a["is_pro"] == "True",
        })

    customers = []
    for a in athletes:                       # ~60% of athletes are also customers
        if rnd.random() < 0.6:
            customers.append({
                "accountid": gid("customer", a["contactid"]),
                "name": a["fullname"], "customertypecode": "Individual",
                "primarycontactid": a["contactid"], "emailaddress1": a["emailaddress1"],
                "address1_country": a["address1_country"],
                "createdon": (REFERENCE_DATE - timedelta(days=rnd.randint(30, 900))).isoformat() + "Z",
            })
    for i in range(1, 26):                   # clubs and sponsors
        kind = rnd.choice(["Club", "Sponsor"])
        country = rnd.choice(sorted({l["country"] for l in locs.values()}))
        customers.append({
            "accountid": gid("customer", f"org{i}"),
            "name": f"{rnd.choice(['Apex','Summit','Tri','Iron','Harbor','Coastal','Alpine','Velo'])} "
                    f"{rnd.choice(['Endurance','Triathlon','Racing','Sports'])} {kind} {i}",
            "customertypecode": kind, "primarycontactid": None,
            "emailaddress1": f"contact{i}@example.com", "address1_country": country,
            "createdon": (REFERENCE_DATE - timedelta(days=rnd.randint(100, 1200))).isoformat() + "Z",
        })

    topics = {
        "Registration": ["Cannot complete registration", "Bib number not received", "Wrong age group on entry"],
        "Refund": ["Refund request after injury", "Duplicate payment charged", "Refund status enquiry"],
        "Transfer": ["Transfer entry to another athlete", "Deferral to next year", "Switch to another event"],
        "Medical": ["Medical certificate upload", "Accessibility accommodation request"],
        "Info": ["Course map question", "Athlete guide not received", "Wave start time enquiry"],
    }
    cases = []
    for n in range(1, 301):
        ctype = rnd.choice(list(topics))
        cust = rnd.choice(customers)
        ev = rnd.choice(events)
        created = REFERENCE_DATE - timedelta(days=rnd.randint(0, 120), hours=rnd.randint(0, 23))
        state = rnd.choices(["Active", "Resolved", "Cancelled"], [0.4, 0.5, 0.1])[0]
        cases.append({
            "incidentid": gid("case", n), "ticketnumber": f"CAS-{n:05d}",
            "title": rnd.choice(topics[ctype]), "casetypecode": ctype,
            "prioritycode": rnd.choices(["High", "Normal", "Low"], [0.15, 0.6, 0.25])[0],
            "statecode": state,
            "statuscode": {"Active": "In Progress", "Resolved": "Problem Solved", "Cancelled": "Cancelled"}[state],
            "_customerid_value": cust["accountid"], "_ironman_eventid_value": ev["ironman_eventid"],
            "description": f"Synthetic case about {ev['ironman_name']}.",
            "createdon": created.isoformat() + "Z", "modifiedon": created.isoformat() + "Z",
        })
    return {"events": events, "athletes": athletes, "customers": customers, "cases": cases}


SEED_DATA = build_data()
DB: dict[str, list[dict]] = deepcopy(SEED_DATA)

ENTITIES = {  # url name -> (primary key, odata entity set name)
    "events": ("ironman_eventid", "ironman_events"),
    "athletes": ("contactid", "contacts"),
    "customers": ("accountid", "accounts"),
    "cases": ("incidentid", "incidents"),
}

# ---------------------------------------------------------------- errors (Dynamics format)
class ODataError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: Optional[dict] = None):
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


app = FastAPI(
    title="Mock Dynamics 365 Events API",
    version="1.0.0",
    description=("Local mock of a Dynamics 365 Web API (OData v4 style) for IRONMAN events, athletes, "
                 "customers and cases. Deterministic synthetic data - safe for integration development "
                 "without sandbox access.\n\nSupports `$filter`, `$select`, `$orderby`, `$top`, `$skip`, "
                 "`$count`; Dynamics-style errors; failure injection via the `X-Mock-Fail` header "
                 "(401, 404, 429, 500, 503)."),
)


@app.exception_handler(ODataError)
async def odata_error_handler(_: Request, exc: ODataError):
    return JSONResponse({"error": {"code": exc.code, "message": exc.message}},
                        status_code=exc.status, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    msg = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
    return JSONResponse({"error": {"code": "0x80060888", "message": f"Invalid request: {msg}"}}, status_code=400)


FAIL_MODES = {
    "401": (401, "0x80072ee7", "Authorization has been denied (injected failure)."),
    "404": (404, "0x80040217", "Entity does not exist (injected failure)."),
    "429": (429, "0x80072321", "Number of requests exceeded the limit (injected failure)."),
    "500": (500, "0x80040216", "An unexpected error occurred (injected failure)."),
    "503": (503, "0x80072322", "Service temporarily unavailable (injected failure)."),
}


def guard(authorization: Optional[str] = Header(None), x_mock_fail: Optional[str] = Header(None)):
    if x_mock_fail:
        if x_mock_fail not in FAIL_MODES:
            raise ODataError(400, "0x80060888", f"X-Mock-Fail must be one of {sorted(FAIL_MODES)}")
        s, c, m = FAIL_MODES[x_mock_fail]
        raise ODataError(s, c, m, {"Retry-After": "2"} if s in (429, 503) else {})
    if AUTH_ENABLED and authorization != f"Bearer {TOKEN}":
        raise ODataError(401, "0x80072ee7", "Missing or invalid bearer token.", {"WWW-Authenticate": "Bearer"})


# ---------------------------------------------------------------- OData query engine
_TOKEN = re.compile(r"""\s*(?:(contains|startswith)\(\s*(\w+)\s*,\s*'((?:[^']|'')*)'\s*\)
                         |(\w+)\s+(eq|ne|gt|ge|lt|le)\s+('(?:[^']|'')*'|true|false|null|-?\d+(?:\.\d+)?))\s*""", re.X | re.I)


def _lit(s: str):
    if s.startswith("'"):
        return s[1:-1].replace("''", "'")
    return {"true": True, "false": False, "null": None}.get(s.lower(), float(s) if "." in s else int(s))


def parse_filter(expr: str, fields: set[str]):
    """Supports: field op literal, contains(f,'x'), startswith(f,'x'), joined with 'and'."""
    conds, parts = [], re.split(r"\s+and\s+", expr.strip(), flags=re.I)
    for p in parts:
        m = _TOKEN.fullmatch(p)
        if not m:
            raise ODataError(400, "0x80060888", f"Unsupported or invalid $filter clause: '{p}'. "
                                                 "Supported: eq ne gt ge lt le, contains(), startswith(), and.")
        fn, fa, fv, f, op, v = m.groups()
        field = fa or f
        if field not in fields:
            raise ODataError(400, "0x80060888", f"Could not find a property named '{field}'.")
        conds.append((fn.lower(), field, fv.replace("''", "'")) if fn else (op.lower(), field, _lit(v)))

    def test(row):
        for op, f, v in conds:
            x = row.get(f)
            if op == "contains":
                ok = x is not None and v.lower() in str(x).lower()
            elif op == "startswith":
                ok = x is not None and str(x).lower().startswith(v.lower())
            elif op == "eq":
                ok = x == v
            elif op == "ne":
                ok = x != v
            else:
                if x is None or v is None:
                    return False
                try:
                    ok = {"gt": x > v, "ge": x >= v, "lt": x < v, "le": x <= v}[op]
                except TypeError:
                    ok = False
            if not ok:
                return False
        return True
    return test


def run_query(name: str, request: Request, top, skip, filter_, select, orderby, count):
    pk, setname = ENTITIES[name]
    rows = DB[name]
    fields = set(rows[0]) if rows else set()
    q = request.query_params
    if any(k.startswith("$") and k not in {"$top", "$skip", "$filter", "$select", "$orderby", "$count"} for k in q):
        bad = [k for k in q if k.startswith("$") and k not in {"$top", "$skip", "$filter", "$select", "$orderby", "$count"}]
        raise ODataError(400, "0x80060888", f"Unsupported query option(s): {', '.join(bad)}")
    if filter_:
        t = parse_filter(filter_, fields)
        rows = [r for r in rows if t(r)]
    if orderby:
        for part in reversed([p.strip() for p in orderby.split(",")]):
            bits = part.split()
            f, desc = bits[0], len(bits) > 1 and bits[1].lower() == "desc"
            if f not in fields:
                raise ODataError(400, "0x80060888", f"Could not find a property named '{f}' for $orderby.")
            rows = sorted(rows, key=lambda r: (r.get(f) is None, r.get(f) if r.get(f) is not None else 0), reverse=desc)
    total = len(rows)
    size = DEFAULT_PAGE if top is None else top
    if size < 1 or size > MAX_PAGE:
        raise ODataError(400, "0x80060888", f"$top must be between 1 and {MAX_PAGE}.")
    if skip < 0:
        raise ODataError(400, "0x80060888", "$skip must be >= 0.")
    page = rows[skip: skip + size]
    if select:
        cols = [c.strip() for c in select.split(",")]
        bad = [c for c in cols if c not in fields]
        if bad:
            raise ODataError(400, "0x80060888", f"Could not find a property named '{bad[0]}' for $select.")
        page = [{c: r[c] for c in cols} for r in page]
    base = str(request.base_url).rstrip("/")
    body: dict[str, Any] = {"@odata.context": f"{base}{API_BASE}/$metadata#{setname}", "value": page}
    if count:
        body["@odata.count"] = total
    if skip + size < total:
        nxt = dict(q)
        nxt["$skip"] = str(skip + size)
        nxt["$top"] = str(size)
        body["@odata.nextLink"] = f"{base}{request.url.path}?" + "&".join(f"{k}={v}" for k, v in nxt.items())
    return body


def make_routes(name: str):
    pk, _ = ENTITIES[name]

    @app.get(f"{API_BASE}/{name}", name=f"list_{name}", tags=[name],
             summary=f"List {name} (OData query options: $filter $select $orderby $top $skip $count)")
    async def list_(request: Request, _=Depends(guard),
                    top: Optional[int] = Query(None, alias="$top", description=f"Page size (1-{MAX_PAGE}, default {DEFAULT_PAGE})"),
                    skip: int = Query(0, alias="$skip", description="Rows to skip"),
                    filter_: Optional[str] = Query(None, alias="$filter", description="e.g. ironman_country eq 'Australia' and ironman_capacity gt 1000"),
                    select: Optional[str] = Query(None, alias="$select", description="Comma-separated fields"),
                    orderby: Optional[str] = Query(None, alias="$orderby", description="e.g. ironman_eventdate desc"),
                    count: bool = Query(False, alias="$count", description="Include @odata.count")):
        return run_query(name, request, top, skip, filter_, select, orderby, count)

    @app.get(f"{API_BASE}/{name}/{{rid}}", name=f"get_{name}", tags=[name], summary=f"Get one of {name} by id")
    @app.get(f"{API_BASE}/{name}({{rid}})", include_in_schema=False)
    async def get_(rid: str, request: Request, _=Depends(guard)):
        rid = rid.strip("()")
        row = next((r for r in DB[name] if r[pk] == rid), None)
        if not row:
            raise ODataError(404, "0x80040217", f"{name[:-1].capitalize()} With Id = {rid} Does Not Exist")
        return {"@odata.context": f"{str(request.base_url).rstrip('/')}{API_BASE}/$metadata#{ENTITIES[name][1]}/$entity", **row}


for _n in ENTITIES:
    make_routes(_n)


# ---------------------------------------------------------------- case create / update / delete
class CaseCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    casetypecode: str = Field(..., pattern="^(Registration|Refund|Transfer|Medical|Info)$")
    prioritycode: str = Field("Normal", pattern="^(High|Normal|Low)$")
    description: Optional[str] = None
    customer_id: str = Field(..., description="accountid of an existing customer")
    event_id: Optional[str] = Field(None, description="ironman_eventid of an existing event")


class CaseUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=200)
    prioritycode: Optional[str] = Field(None, pattern="^(High|Normal|Low)$")
    description: Optional[str] = None
    statecode: Optional[str] = Field(None, pattern="^(Active|Resolved|Cancelled)$")


_STATUS = {"Active": "In Progress", "Resolved": "Problem Solved", "Cancelled": "Cancelled"}


@app.post(f"{API_BASE}/cases", status_code=201, tags=["cases"], summary="Create a case")
async def create_case(body: CaseCreate, _=Depends(guard)):
    if not any(c["accountid"] == body.customer_id for c in DB["customers"]):
        raise ODataError(400, "0x80040217", f"Customer With Id = {body.customer_id} Does Not Exist")
    if body.event_id and not any(e["ironman_eventid"] == body.event_id for e in DB["events"]):
        raise ODataError(400, "0x80040217", f"Event With Id = {body.event_id} Does Not Exist")
    n = len(DB["cases"]) + 1
    now = REFERENCE_DATE.isoformat() + "Z"          # fixed clock keeps test data deterministic
    row = {"incidentid": gid("case", n), "ticketnumber": f"CAS-{n:05d}", "title": body.title,
           "casetypecode": body.casetypecode, "prioritycode": body.prioritycode, "statecode": "Active",
           "statuscode": "In Progress", "_customerid_value": body.customer_id,
           "_ironman_eventid_value": body.event_id, "description": body.description or "",
           "createdon": now, "modifiedon": now}
    DB["cases"].append(row)
    log.info("created case %s", row["ticketnumber"])
    return JSONResponse(row, status_code=201, headers={"OData-EntityId": f"{API_BASE}/cases({row['incidentid']})"})


@app.patch(f"{API_BASE}/cases/{{rid}}", tags=["cases"], summary="Update a case")
async def update_case(rid: str, body: CaseUpdate, _=Depends(guard)):
    row = next((r for r in DB["cases"] if r["incidentid"] == rid), None)
    if not row:
        raise ODataError(404, "0x80040217", f"Case With Id = {rid} Does Not Exist")
    for k, v in body.model_dump(exclude_none=True).items():
        row[k] = v
        if k == "statecode":
            row["statuscode"] = _STATUS[v]
    row["modifiedon"] = REFERENCE_DATE.isoformat() + "Z"
    return row


@app.delete(f"{API_BASE}/cases/{{rid}}", status_code=204, tags=["cases"], summary="Delete a case")
async def delete_case(rid: str, _=Depends(guard)):
    n = len(DB["cases"])
    DB["cases"] = [r for r in DB["cases"] if r["incidentid"] != rid]
    if len(DB["cases"]) == n:
        raise ODataError(404, "0x80040217", f"Case With Id = {rid} Does Not Exist")
    return JSONResponse(None, status_code=204)


# ---------------------------------------------------------------- utility
@app.post("/mock/reset", tags=["mock"], summary="Reset all data to the deterministic seed state")
async def reset(_=Depends(guard)):
    DB.clear()
    DB.update(deepcopy(SEED_DATA))
    return {"status": "reset", "counts": {k: len(v) for k, v in DB.items()}}


@app.get("/health", tags=["mock"], summary="Health check (no auth)")
async def health():
    return {"status": "ok", "env": ENV, "auth_enabled": AUTH_ENABLED, "counts": {k: len(v) for k, v in DB.items()}}
