# POC-003 - Mock Dynamics 365 Events API

A local FastAPI service that behaves like a Dynamics 365 Web API (OData v4 style) for IRONMAN
**events, athletes, customers and cases**, so Dynamics integration logic can be built and tested
**without sandbox access**.

- Data: events/athletes come from POC-001 (`data/*.csv`); customers and cases are generated with a
  fixed seed (42). GUIDs are deterministic (uuid5), so every run on every machine is identical.
- Base URL: `http://localhost:8100/api/data/v9.2`   Docs: `http://localhost:8100/docs`

## Run (Windows PowerShell)

```
cd poc3
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app:app --reload --port 8100
```

## Try it

Auth is a dummy bearer token from `.env` (`MOCK_TOKEN`; set `MOCK_AUTH_ENABLED=false` to turn it off).

```
$h = @{ Authorization = "Bearer dev-token-change-me" }
Invoke-RestMethod -Headers $h "http://localhost:8100/api/data/v9.2/events?`$top=3&`$count=true"
Invoke-RestMethod -Headers $h "http://localhost:8100/api/data/v9.2/events?`$filter=ironman_country eq 'Australia'&`$orderby=ironman_eventdate"
```

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/events`, `/athletes`, `/customers`, `/cases` | filter, select, orderby, paging |
| GET | `/{entity}/{id}` or `/{entity}({id})` | 404 in Dynamics error format if missing |
| POST | `/cases` | create (validated), returns 201 + `OData-EntityId` |
| PATCH | `/cases/{id}` | update title/priority/description/state |
| DELETE | `/cases/{id}` | 204, or 404 |
| POST | `/mock/reset` | back to the deterministic seed state |
| GET | `/health` | no auth |

(all under `/api/data/v9.2` except `/mock/*` and `/health`)

## Query options

`$filter` (`eq ne gt ge lt le`, `contains()`, `startswith()`, joined with `and`), `$select`, `$orderby`,
`$top` (default 50, max 200), `$skip`, `$count=true`. Results carry `@odata.context`, `@odata.count`
and `@odata.nextLink` when more pages exist. Unsupported options return 400.

## Errors and failure testing

Errors use the Dynamics shape: `{"error": {"code": "0x...", "message": "..."}}`
(400 bad query / validation, 401, 404, 429, 500, 503).

To test retry and error handling in your integration, add a header `X-Mock-Fail: 401|404|429|500|503`
to any request. 429 and 503 also return `Retry-After: 2`.

## Deliverables

- `app.py` - the service
- `openapi.json` - OpenAPI specification (also live at `/openapi.json`)
- `sample_payloads/` - 14 request/response examples (paging, filter, create case, all error types)
- `test_api.py` - 12 tests (`pytest -q`)
- `.env.example` - configuration, no secrets in code
- `export_artifacts.py` - regenerates `openapi.json` and `sample_payloads/`

## Limits (it is a mock)

- Data is in memory; restart or `POST /mock/reset` restores the seed state.
- `@odata.nextLink` uses `$skip`, not Dynamics' real paging cookie.
- Field names are IRONMAN-style custom columns (`ironman_*`), not a real Dynamics schema.
- Write operations exist for cases only.
