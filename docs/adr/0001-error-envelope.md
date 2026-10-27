# ADR 0001: Consistent Error Envelope

## Status
Accepted

## Context
API consumers require a predictable contract for both success and error responses. Ad-hoc error structures complicate client error handling.

## Decision
All endpoints return responses wrapped in a uniform schema:
- Success: `{"success": true, "data": <T>, "error": null}`
- Error: `{"success": false, "data": null, "error": {"code": "...", "message": "...", "field": null}}`

Error responses are formalized with the concrete `ErrorResponse` schema and `ErrorCode` enumeration. Starlette and FastAPI HTTP exceptions, validation errors (422), and unexpected server errors (500) are mapped to this envelope.

## Consequences
Clients parse a single envelope shape across all endpoints and status codes. Internal traceback details are kept server-side and never leaked in error payloads.
