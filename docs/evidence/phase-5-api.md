# Phase 5 Step 5 local API evidence — 2026-11-11

`PHASE5_DYNAMODB_API_TEST=1` with `.venv\Scripts\python -m unittest
tests.test_phase5_api -v` passed one integration test against two real HTTP service
processes and the pinned DynamoDB Local 2.6.1 container. Tables were bootstrapped locally.
The test wrote four unique windows to each owned table and checked both OpenAPI documents,
required intersection filters, pagination and query-scoped cursors, cross-intersection
isolation, UTC fractional time boundaries, empty ranges, invalid parameters, detail lookups
and 404s. It verified exact JSON decimal output, then stopped the local store and observed
503 from both APIs while `/healthz` stayed 200. Reads returned 200 after the store restarted.
The test removed only its own records and processes.

`scripts/smoke.py` passed all eight service entry points, including the two new list
routes. The normal Python suite passed **45 tests** with three opt-in local container
tests skipped; `git diff --check` and Python compilation passed.

This is local API/storage evidence. Managed DynamoDB, cloud IAM, public ingress and an
integrated cloud deployment are not verified. See [API usage](../phase-5-api.md).
