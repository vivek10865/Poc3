"""Run: pytest -q   (or python test_api.py)"""
import os
os.environ["MOCK_AUTH_ENABLED"] = "true"
os.environ["MOCK_TOKEN"] = "t"
from fastapi.testclient import TestClient
import app as A

c = TestClient(A.app)
H = {"Authorization": "Bearer t"}
B = A.API_BASE


def setup_function(_):
    c.post("/mock/reset", headers=H)


def test_health_no_auth():
    assert c.get("/health").json()["counts"] == {"events": 34, "athletes": 520, "customers": 333, "cases": 300}

def test_auth_required():
    r = c.get(f"{B}/events")
    assert r.status_code == 401 and r.json()["error"]["code"] == "0x80072ee7"
    assert c.get(f"{B}/events", headers={"Authorization": "Bearer wrong"}).status_code == 401

def test_deterministic_ids_and_data():
    a = c.get(f"{B}/events?$top=3&$orderby=ironman_eventdate", headers=H).json()["value"]
    assert a[0]["ironman_name"] == "IRONMAN Kona" and a[0]["ironman_eventid"] == A.gid("event", 1)
    assert A.build_data() == A.SEED_DATA          # rebuilding gives byte-identical records

def test_pagination():
    r = c.get(f"{B}/athletes?$top=100&$count=true", headers=H).json()
    assert r["@odata.count"] == 520 and len(r["value"]) == 100 and "@odata.nextLink" in r
    seen, url = [], f"{B}/athletes?$top=200&$orderby=athleteno"
    seen_ids, skip = set(), 0
    while True:
        j = c.get(f"{B}/athletes?$top=200&$skip={skip}&$orderby=ironman_athleteno", headers=H).json()
        seen_ids |= {x["contactid"] for x in j["value"]}
        if "@odata.nextLink" not in j: break
        skip += 200
    assert len(seen_ids) == 520
    assert c.get(f"{B}/athletes?$top=0", headers=H).status_code == 400
    assert c.get(f"{B}/athletes?$top=9999", headers=H).status_code == 400
    assert c.get(f"{B}/athletes?$top=abc", headers=H).status_code == 400
    assert c.get(f"{B}/athletes?$skip=-1", headers=H).status_code == 400

def test_filter():
    j = c.get(f"{B}/events?$filter=ironman_country eq 'Australia'&$count=true", headers=H).json()
    expect = [e for e in A.SEED_DATA["events"] if e["ironman_country"] == "Australia"]
    assert j["@odata.count"] == len(expect) > 0
    j = c.get(f"{B}/events?$filter=ironman_capacity gt 2000 and statuscode eq 'COMPLETED'", headers=H).json()["value"]
    assert all(e["ironman_capacity"] > 2000 and e["statuscode"] == "COMPLETED" for e in j)
    j = c.get(f"{B}/athletes?$filter=contains(lastname,'john')", headers=H).json()["value"]
    assert j and all("john" in a["lastname"].lower() for a in j)
    j = c.get(f"{B}/events?$filter=ironman_eventdate ge '2026-10-01'", headers=H).json()["value"]
    assert j and all(e["ironman_eventdate"] >= "2026-10-01" for e in j)
    assert c.get(f"{B}/events?$filter=nope eq 1", headers=H).status_code == 400
    assert c.get(f"{B}/events?$filter=garbage", headers=H).status_code == 400
    assert c.get(f"{B}/events?$expand=x", headers=H).status_code == 400

def test_select_orderby():
    j = c.get(f"{B}/events?$select=ironman_name,ironman_capacity&$orderby=ironman_capacity desc&$top=2", headers=H).json()["value"]
    assert set(j[0]) == {"ironman_name", "ironman_capacity"} and j[0]["ironman_capacity"] >= j[1]["ironman_capacity"]
    assert c.get(f"{B}/events?$select=bogus", headers=H).status_code == 400

def test_get_by_id_both_styles():
    eid = A.gid("event", 1)
    assert c.get(f"{B}/events/{eid}", headers=H).json()["ironman_name"] == "IRONMAN Kona"
    assert c.get(f"{B}/events({eid})", headers=H).json()["ironman_name"] == "IRONMAN Kona"
    r = c.get(f"{B}/events/00000000-0000-0000-0000-000000000000", headers=H)
    assert r.status_code == 404 and r.json()["error"]["code"] == "0x80040217"

def test_case_lifecycle_and_reset():
    cust, ev = A.SEED_DATA["customers"][0]["accountid"], A.SEED_DATA["events"][0]["ironman_eventid"]
    r = c.post(f"{B}/cases", headers=H, json={"title": "Test refund", "casetypecode": "Refund", "customer_id": cust, "event_id": ev})
    assert r.status_code == 201 and r.json()["ticketnumber"] == "CAS-00301"
    cid = r.json()["incidentid"]
    r = c.patch(f"{B}/cases/{cid}", headers=H, json={"statecode": "Resolved"})
    assert r.json()["statuscode"] == "Problem Solved"
    assert c.delete(f"{B}/cases/{cid}", headers=H).status_code == 204
    assert c.get(f"{B}/cases/{cid}", headers=H).status_code == 404
    assert c.delete(f"{B}/cases/{cid}", headers=H).status_code == 404
    c.post(f"{B}/cases", headers=H, json={"title": "Another", "casetypecode": "Info", "customer_id": cust})
    assert c.post("/mock/reset", headers=H).json()["counts"]["cases"] == 300

def test_case_validation_errors():
    cust = A.SEED_DATA["customers"][0]["accountid"]
    assert c.post(f"{B}/cases", headers=H, json={"title": "x"}).status_code == 400
    assert c.post(f"{B}/cases", headers=H, json={"title": "ok title", "casetypecode": "Bad", "customer_id": cust}).status_code == 400
    r = c.post(f"{B}/cases", headers=H, json={"title": "ok title", "casetypecode": "Info", "customer_id": "nope"})
    assert r.status_code == 400 and "Does Not Exist" in r.json()["error"]["message"]
    assert c.patch(f"{B}/cases/zzz", headers=H, json={"title": "valid"}).status_code == 404

def test_failure_injection():
    for code in ("401", "404", "429", "500", "503"):
        r = c.get(f"{B}/events", headers={**H, "X-Mock-Fail": code})
        assert r.status_code == int(code) and "error" in r.json()
    assert c.get(f"{B}/events", headers={**H, "X-Mock-Fail": "429"}).headers["Retry-After"] == "2"
    assert c.get(f"{B}/events", headers={**H, "X-Mock-Fail": "418"}).status_code == 400

def test_referential_integrity():
    cust = {x["accountid"] for x in A.SEED_DATA["customers"]}
    ev = {x["ironman_eventid"] for x in A.SEED_DATA["events"]}
    ath = {x["contactid"] for x in A.SEED_DATA["athletes"]}
    assert all(k["_customerid_value"] in cust and k["_ironman_eventid_value"] in ev for k in A.SEED_DATA["cases"])
    assert all(x["primarycontactid"] in ath for x in A.SEED_DATA["customers"] if x["primarycontactid"])

def test_openapi_has_all_paths():
    paths = c.get("/openapi.json").json()["paths"]
    for n in ("events", "athletes", "customers", "cases"):
        assert f"{B}/{n}" in paths and f"{B}/{n}/{{rid}}" in paths
    assert "post" in paths[f"{B}/cases"]

if __name__ == "__main__":
    import sys, pytest
    sys.exit(pytest.main(["-q", __file__]))
