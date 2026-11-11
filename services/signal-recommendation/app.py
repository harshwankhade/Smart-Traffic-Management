"""Signal Recommendation liveness and opt-in Kafka result processing."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from recommendation import recommend
from recommendation.repository import RecommendationRepository
from traffic_contracts.result_consumer import ResultConsumer
from traffic_contracts.window_api import json_response, query_page


def create_app(repository=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.worker = None
        app.state.repository = repository
        if os.getenv("PHASE5_CONSUMER_ENABLED") == "1":
            owned = repository or RecommendationRepository()
            app.state.repository = owned
            app.state.worker = ResultConsumer(
                "signal-recommendation-v1", owned.store,
                lambda result: owned.put(recommend(result)))
            app.state.worker.start()
        try:
            yield
        finally:
            if app.state.worker:
                app.state.worker.stop()

    app = FastAPI(title="Signal Recommendation", version="1.0", lifespan=lifespan)

    def owned_repository():
        owned = getattr(app.state, "repository", None)
        if owned is None:
            owned = RecommendationRepository()
            app.state.repository = owned
        return owned

    @app.get("/healthz")
    def health():
        return {"service": "signal-recommendation", "status": "ok", "scope": "scaffold"}

    @app.get("/readyz")
    def ready():
        worker = getattr(app.state, "worker", None)
        if worker and worker.ready():
            return {"status": "ready", **worker.snapshot()["counts"]}
        return JSONResponse(status_code=503, content={"detail": "Results or storage unavailable",
                                                     **(worker.snapshot()["counts"] if worker else {})})

    @app.get("/recommendations", summary="List stored simulated recommendations")
    def list_recommendations(intersection_id: str = Query(...),
                             from_: str | None = Query(None, alias="from"),
                             to: str | None = Query(None),
                             limit: int = Query(50, ge=1, le=100),
                             cursor: str | None = Query(None)):
        try:
            page = query_page(owned_repository(), "recommendations", intersection_id,
                              from_time=from_, to_time=to, limit=limit, cursor=cursor)
            return json_response(page)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=503, detail="Recommendation storage unavailable") from error

    @app.get("/recommendations/{recommendation_id:path}",
             summary="Get one stored simulated recommendation")
    def get_recommendation(recommendation_id: str, intersection_id: str = Query(...)):
        if not intersection_id.strip():
            raise HTTPException(status_code=422, detail="intersection_id is invalid")
        try:
            item = owned_repository().get(intersection_id, recommendation_id)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=503, detail="Recommendation storage unavailable") from error
        if item is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        return json_response(item)

    return app


app = create_app()
