"""Writes openapi.json and sample_payloads/*.json from the running app code (deterministic)."""
import json, os
os.environ["MOCK_AUTH_ENABLED"] = "false"
from pathlib import Path
from fastapi.testclient import TestClient
import app as A

c, B, out = TestClient(A.app, base_url="http://localhost:8100"), A.API_BASE, Path("sample_payloads")
out.mkdir(exist_ok=True)
Path("openapi.json").write_text(json.dumps(c.get("/openapi.json").json(), indent=2))

def save(name, obj):
    (out / f"{name}.json").write_text(json.dumps(obj, indent=2, ensure_ascii=False))

ev = c.get(f"{B}/events?$top=2&$count=true").json()
save("events_list_paged", ev)
save("events_filtered_australia", c.get(f"{B}/events?$filter=ironman_country eq 'Australia'&$select=ironman_name,ironman_eventdate,ironman_city&$orderby=ironman_eventdate").json())
save("event_by_id", c.get(f"{B}/events/{ev['value'][0]['ironman_eventid']}").json())
save("athletes_list", c.get(f"{B}/athletes?$top=2").json())
save("customers_list", c.get(f"{B}/customers?$top=2&$filter=customertypecode eq 'Club'").json())
case = c.get(f"{B}/cases?$top=1&$filter=statecode eq 'Active'").json()
save("cases_list", case)
cust, evid = A.SEED_DATA["customers"][0]["accountid"], A.SEED_DATA["events"][0]["ironman_eventid"]
req = {"title": "Refund request after injury", "casetypecode": "Refund", "prioritycode": "High",
       "description": "Athlete injured before race week.", "customer_id": cust, "event_id": evid}
save("case_create_request", req)
save("case_create_response_201", c.post(f"{B}/cases", json=req).json())
save("case_update_request", {"statecode": "Resolved"})
save("error_404_not_found", c.get(f"{B}/events/00000000-0000-0000-0000-000000000000").json())
save("error_400_bad_filter", c.get(f"{B}/events?$filter=nope eq 1").json())
save("error_400_validation", c.post(f"{B}/cases", json={"title": "x"}).json())
save("error_401_unauthorized", {"error": {"code": "0x80072ee7", "message": "Missing or invalid bearer token."}})
save("error_429_throttled", {"error": {"code": "0x80072321", "message": "Number of requests exceeded the limit (injected failure)."}})
c.post("/mock/reset")
print("wrote openapi.json and", len(list(out.glob('*.json'))), "sample payloads")
