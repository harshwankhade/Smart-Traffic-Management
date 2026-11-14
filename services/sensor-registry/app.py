"""Registry API; all domain writes belong to the Registry schema."""
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from registry import repository as repo
from registry.database import Database
from registry.models import IntersectionRow, SensorRow
from registry.schemas import (Intersection, IntersectionCreate, IntersectionPatch,
                              Sensor, SensorCreate, SensorPatch)


def create_app(database_url=None):
    database = Database(database_url)

    @asynccontextmanager
    async def lifespan(app):
        try:
            database.initialize(create_tables=os.getenv("CREATE_DATABASE_SCHEMA") == "1")
            yield
        finally:
            database.engine.dispose()

    app = FastAPI(title="Sensor Registry", version="1.0", lifespan=lifespan)
    app.state.database = database

    def session():
        with database.sessions() as value:
            yield value

    @app.exception_handler(IntegrityError)
    async def conflict(_, error):
        return JSONResponse(status_code=409, content={"detail": "Record ID already exists or conflicts with stored data"})

    @app.exception_handler(SQLAlchemyError)
    async def unavailable(_, error):
        return JSONResponse(status_code=503, content={"detail": "Registry database unavailable"})

    @app.get("/healthz")
    def health():
        return {"service": "sensor-registry", "status": "ok", "scope": "scaffold"}

    def required(row, label):
        if row is None:
            raise HTTPException(404, f"{label} not found")
        return row

    @app.post("/intersections", status_code=201, response_model=Intersection)
    def create_intersection(body: IntersectionCreate, db=Depends(session)):
        return repo.create(db, IntersectionRow, body.model_dump(exclude={"schema_version"}))

    @app.get("/intersections/{identifier}", response_model=Intersection)
    def read_intersection(identifier: str, db=Depends(session)):
        return required(repo.get_intersection(db, identifier), "Intersection")

    @app.patch("/intersections/{identifier}", response_model=Intersection)
    def patch_intersection(identifier: str, body: IntersectionPatch, db=Depends(session)):
        return repo.update(db, required(repo.get_intersection(db, identifier), "Intersection"),
                           body.model_dump(exclude_unset=True))

    @app.post("/sensors", status_code=201, response_model=Sensor)
    def create_sensor(body: SensorCreate, db=Depends(session)):
        if repo.get_sensor(db, body.sensor_id):
            raise HTTPException(409, "Sensor ID already exists")
        if not repo.get_intersection(db, body.intersection_id):
            raise HTTPException(422, "Unknown intersection reference")
        return repo.create(db, SensorRow, body.model_dump(exclude={"schema_version"}))

    @app.get("/sensors/{identifier}", response_model=Sensor)
    def read_sensor(identifier: str, db=Depends(session)):
        return required(repo.get_sensor(db, identifier), "Sensor")

    @app.patch("/sensors/{identifier}", response_model=Sensor)
    def patch_sensor(identifier: str, body: SensorPatch, db=Depends(session)):
        return repo.update(db, required(repo.get_sensor(db, identifier), "Sensor"),
                           body.model_dump(exclude_unset=True))

    return app


app = create_app()
