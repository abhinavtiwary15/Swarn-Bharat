# ADR 0001: Consistent Response Envelopes

## Status
Accepted

## Context
API consumers require a predictable contract for both success and error responses. Ad-hoc error structures complicate client error handling.

## Decision
All endpoints return responses wrapped in uniform schema envelopes:
- Success: `SuccessEnvelope[T]` -> `{"success": true, "data": <T>, "error": null}`
- Error: `ErrorResponse` -> `{"success": false, "data": null, "error": {"code": "...", "message": "...", "field": null}}`

Concrete response classes (e.g., `HealthEnvelope`) inherit from `SuccessEnvelope[T]` to avoid generic schema naming in OpenAPI. Error responses are formalized with the concrete `ErrorResponse` schema and `ErrorCode` enumeration. Starlette and FastAPI HTTP exceptions, validation errors (422), and unexpected server errors (500) are mapped to `ErrorResponse`.

## Consequences
Clients parse a single envelope shape across all endpoints and status codes. Internal traceback details are kept server-side and never leaked in error payloads.
