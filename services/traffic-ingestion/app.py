"""Validated REST readings -> Registry lookup -> real Publisher gRPC."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

from traffic_contracts.reading import Reading
from ingestion.clients import PublisherClient, RegistryClient


def create_app(registry=None, publisher=None):
    registry = registry or RegistryClient(os.environ.get("SENSOR_REGISTRY_URL", "http://127.0.0.1:8001"))
    publisher = publisher or PublisherClient(os.environ.get("PUBLISHER_GRPC_TARGET", "127.0.0.1:50051"),
                                             os.environ.get("PUBLISHER_HTTP_URL", "http://127.0.0.1:8003"))

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            registry.close()
            publisher.close()

    app = FastAPI(title="Traffic Ingestion", version="1.0", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid(_, error):
        body = error.body
        # Do not echo invalid inputs (including NaN/Infinity) or validation exceptions.
        details = [{"loc": item["loc"], "msg": item["msg"], "type": item["type"]} for item in error.errors()]
        result = {"detail": jsonable_encoder(details)}
        if isinstance(body, dict) and isinstance(body.get("event_id"), str):
            result["event_id"] = body["event_id"]
        return JSONResponse(status_code=422, content=result)

    @app.get("/healthz")
    def health():
        return {"service": "traffic-ingestion", "status": "ok", "scope": "scaffold"}

    @app.get("/readyz")
    def ready():
        try:
            registry.ready()
            publisher.ready()
            return {"status": "ready"}
        except Exception:
            return JSONResponse(status_code=503, content={"detail": "Registry or publisher unavailable"})

    @app.post("/readings", status_code=202)
    def ingest(reading: Reading):
        try:
            registry.validate(reading)
            publisher.publish(reading)
        except HTTPException as error:
            return JSONResponse(status_code=error.status_code, content={"event_id": reading.event_id, "detail": error.detail})
        except Exception:
            return JSONResponse(status_code=500, content={"event_id": reading.event_id, "detail": "Unexpected ingestion failure"})
        return {"event_id": reading.event_id, "accepted": True}

    return app


app = create_app()
