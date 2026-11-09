"""Phase 1 health endpoint only; no domain API."""

from fastapi import FastAPI

app = FastAPI(title="signal-recommendation scaffold", docs_url=None,
              redoc_url=None, openapi_url=None)


@app.get("/healthz")
def health():
    return {"service": "signal-recommendation", "status": "ok", "scope": "scaffold"}
