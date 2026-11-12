"""One Event Publisher process exposing HTTP health and the actual gRPC service."""
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import grpc
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from traffic_contracts import publisher_pb2_grpc
from publisher.adapters import KafkaSink, S3Archive
from publisher.coordination import SinglePublisher, ZooKeeperElection, enabled_from_environment
from publisher.recovery import HttpRecoveryReporter
from publisher.service import Publisher


class NotReady(publisher_pb2_grpc.EventPublisherServicer):
    def PublishReading(self, request, context):
        context.abort(grpc.StatusCode.UNAVAILABLE, "Publisher dependencies not configured")


def create_app(archive=None, sink=None, coordination=None):
    @asynccontextmanager
    async def lifespan(app):
        # Missing local credentials mean unready, not a false acceptance path.
        try:
            app.state.archive = archive or S3Archive()
            app.state.sink = sink or KafkaSink()
            reporter = (HttpRecoveryReporter(os.environ.get("TRAFFIC_ANALYTICS_URL", "http://127.0.0.1:8008"))
                        if os.environ.get("RECOVERY_EVENTS_ENABLED") == "1" else None)
            app.state.reporter = reporter
            app.state.coordination = coordination or (ZooKeeperElection(reporter=reporter) if enabled_from_environment() else SinglePublisher())
            app.state.coordination.start()
            app.state.service = Publisher(app.state.archive, app.state.sink, app.state.coordination)
        except Exception:
            app.state.service = None
        server = grpc.server(ThreadPoolExecutor(max_workers=4),
                             options=[("grpc.max_receive_message_length", 65536)])
        publisher_pb2_grpc.add_EventPublisherServicer_to_server(app.state.service or NotReady(), server)
        bound = server.add_insecure_port(os.environ.get("PUBLISHER_GRPC_BIND", "127.0.0.1:50051"))
        if not bound:
            raise RuntimeError("Unable to bind publisher gRPC address")
        app.state.grpc_port = bound
        server.start()
        try:
            yield
        finally:
            server.stop(2).wait()
            for name in ("sink", "archive"):
                item = getattr(app.state, name, None)
                if item:
                    item.close()
            item = getattr(app.state, "coordination", None)
            if item:
                item.stop()
            item = getattr(app.state, "reporter", None)
            if item:
                item.close()

    app = FastAPI(title="Event Publisher", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.get("/healthz")
    def health():
        return {"service": "event-publisher", "status": "ok", "scope": "scaffold"}

    @app.get("/readyz")
    def ready():
        try:
            if not getattr(app.state, "service", None):
                raise RuntimeError("Dependencies not configured")
            app.state.archive.ready()
            app.state.sink.ready()
            if not app.state.coordination.ready():
                raise RuntimeError("Not elected ZooKeeper leader")
            return {"status": "ready", "grpc_port": app.state.grpc_port,
                    "coordination": app.state.coordination.status()}
        except Exception:
            return JSONResponse(status_code=503, content={"detail": "Archive or Kafka unavailable"})

    @app.get("/coordination")
    def coordination_status():
        coordinator = getattr(app.state, "coordination", None)
        if not coordinator:
            return JSONResponse(status_code=503, content={"detail": "Publisher not started"})
        return coordinator.status()

    return app


app = create_app()
