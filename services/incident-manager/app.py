"""Incident API; Registry is queried over REST, never through its database."""
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError

from incidents import repository as repo
from incidents.database import Database
from incidents.registry_client import RegistryClient
from incidents.schemas import Incident, IncidentCreate, IncidentPatch
from incidents.outbox import OutboxWorker
from traffic_contracts.alerts import SqsAlertSender


def create_app(database_url=None, registry_url=None, registry_transport=None, alert_sender=None):
    database = Database(database_url)
    registry = RegistryClient(registry_url or os.environ.get("SENSOR_REGISTRY_URL", "http://127.0.0.1:8001"),
                              registry_transport)

    @asynccontextmanager
    async def lifespan(app):
        try:
            database.initialize(create_tables=os.getenv("CREATE_DATABASE_SCHEMA") == "1")
            app.state.outbox_worker = None
            sender = alert_sender or (SqsAlertSender() if os.getenv("PHASE6_ALERTS_ENABLED") == "1" else None)
            if sender is not None:
                app.state.outbox_worker = OutboxWorker(database, sender)
                app.state.outbox_worker.start()
            yield
        finally:
            if getattr(app.state, "outbox_worker", None):
                app.state.outbox_worker.stop()
            registry.close()
            database.engine.dispose()

    app = FastAPI(title="Incident Manager", version="1.0", lifespan=lifespan)
    app.state.database = database

    def session():
        with database.sessions() as value:
            yield value

    @app.exception_handler(IntegrityError)
    async def duplicate(_, error):
        return JSONResponse(status_code=409, content={"detail": "Incident ID already exists or conflicts with stored data"})

    @app.exception_handler(StaleDataError)
    async def concurrent_update(_, error):
        return JSONResponse(status_code=409, content={"detail": "Incident changed concurrently; retrieve and retry"})

    @app.exception_handler(SQLAlchemyError)
    async def unavailable(_, error):
        return JSONResponse(status_code=503, content={"detail": "Incident database unavailable"})

    @app.get("/healthz")
    def health():
        return {"service": "incident-manager", "status": "ok", "scope": "scaffold"}

    @app.post("/incidents", status_code=201, response_model=Incident)
    def create_incident(body: IncidentCreate, db=Depends(session)):
        if repo.get(db, body.incident_id):
            raise HTTPException(409, "Incident ID already exists")
        registry.validate_intersection(body.intersection_id)
        return repo.create(db, body.model_dump(exclude={"schema_version"}))

    def required(row):
        if row is None:
            raise HTTPException(404, "Incident not found")
        return row

    @app.get("/incidents/{identifier}", response_model=Incident)
    def read_incident(identifier: str, db=Depends(session)):
        return required(repo.get(db, identifier))

    @app.patch("/incidents/{identifier}", response_model=Incident)
    def patch_incident(identifier: str, body: IncidentPatch, db=Depends(session)):
        try:
            return repo.update(db, required(repo.get(db, identifier)), body.model_dump(exclude_unset=True))
        except repo.InvalidTransition as error:
            raise HTTPException(409, str(error)) from error

    return app


app = create_app()
