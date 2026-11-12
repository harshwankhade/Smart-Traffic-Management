"""Traffic Analytics liveness and opt-in Kafka result processing."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from analytics.repository import SummaryRepository
from analytics.recovery_api import page as recovery_page
from analytics.recovery_repository import RecoveryConflict, RecoveryRepository
from traffic_contracts.recovery import validate_recovery_event
from traffic_contracts.result_consumer import ResultConsumer
from traffic_contracts.window_api import json_response, query_page


def create_app(repository=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.worker = None
        app.state.repository = repository
        app.state.recovery_repository = None
        if os.getenv("PHASE5_CONSUMER_ENABLED") == "1":
            owned = repository or SummaryRepository()
            app.state.repository = owned
            app.state.worker = ResultConsumer("traffic-analytics-v1", owned.store, owned.put)
            app.state.worker.start()
        try:
            yield
        finally:
            if app.state.worker:
                app.state.worker.stop()

    app = FastAPI(title="Traffic Analytics", version="1.0", lifespan=lifespan)

    def owned_repository():
        owned = getattr(app.state, "repository", None)
        if owned is None:
            owned = SummaryRepository()
            app.state.repository = owned
        return owned

    def owned_recovery_repository():
        owned = getattr(app.state, "recovery_repository", None)
        if owned is None:
            owned = RecoveryRepository()
            app.state.recovery_repository = owned
        return owned

    @app.get("/healthz")
    def health():
        return {"service": "traffic-analytics", "status": "ok", "scope": "scaffold"}

    @app.get("/readyz")
    def ready():
        worker = getattr(app.state, "worker", None)
        if worker and worker.ready():
            return {"status": "ready", **worker.snapshot()["counts"]}
        return JSONResponse(status_code=503, content={"detail": "Results or storage unavailable",
                                                     **(worker.snapshot()["counts"] if worker else {})})

    @app.get("/traffic/summaries", summary="List persisted traffic windows")
    def list_summaries(intersection_id: str = Query(...),
                       from_: str | None = Query(None, alias="from"),
                       to: str | None = Query(None),
                       limit: int = Query(50, ge=1, le=100),
                       cursor: str | None = Query(None)):
        try:
            page = query_page(owned_repository(), "summaries", intersection_id,
                              from_time=from_, to_time=to, limit=limit, cursor=cursor)
            return json_response(page)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=503, detail="Traffic summary storage unavailable") from error

    @app.get("/traffic/summaries/{window_id:path}", summary="Get one persisted traffic window")
    def get_summary(window_id: str, intersection_id: str = Query(...)):
        if not intersection_id.strip():
            raise HTTPException(status_code=422, detail="intersection_id is invalid")
        try:
            item = owned_repository().get(intersection_id, window_id)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=503, detail="Traffic summary storage unavailable") from error
        if item is None:
            raise HTTPException(status_code=404, detail="Traffic summary not found")
        return json_response(item)

    @app.post("/internal/recovery-events", status_code=202, include_in_schema=False)
    def record_recovery_event(event: dict):
        try:
            status = owned_recovery_repository().put(validate_recovery_event(event))
            return {"recovery_id": event["recovery_id"], "status": status}
        except RecoveryConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=503, detail="Recovery event storage unavailable") from error

    @app.get("/traffic/recovery-events", summary="List persisted publisher recovery events")
    def list_recovery_events(publisher_id: str = Query(...),
                             from_: str | None = Query(None, alias="from"),
                             to: str | None = Query(None),
                             limit: int = Query(50, ge=1, le=100),
                             cursor: str | None = Query(None)):
        try:
            return json_response(recovery_page(owned_recovery_repository(), publisher_id,
                                               from_time=from_, to_time=to, limit=limit, cursor=cursor))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=503, detail="Recovery event storage unavailable") from error

    @app.get("/traffic/recovery-events/{recovery_id:path}", summary="Get one persisted publisher recovery event")
    def get_recovery_event(recovery_id: str, publisher_id: str = Query(...)):
        try:
            item = owned_recovery_repository().get(publisher_id, recovery_id)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=503, detail="Recovery event storage unavailable") from error
        if item is None:
            raise HTTPException(status_code=404, detail="Recovery event not found")
        return json_response(item)

    return app


app = create_app()
