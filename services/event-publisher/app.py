"""One Event Publisher process exposing HTTP health and the actual gRPC service."""
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import grpc
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from traffic_contracts import publisher_pb2_grpc
from publisher.adapters import KafkaSink, S3Archive
from publisher.service import Publisher


class NotReady(publisher_pb2_grpc.EventPublisherServicer):
    def PublishReading(self, request, context):
        context.abort(grpc.StatusCode.UNAVAILABLE, "Publisher dependencies not configured")


def create_app(archive=None, sink=None):
    @asynccontextmanager
    async def lifespan(app):
        # Missing local credentials mean unready, not a false acceptance path.
        try:
            app.state.archive = archive or S3Archive()
            app.state.sink = sink or KafkaSink()
            app.state.service = Publisher(app.state.archive, app.state.sink)
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
            return {"status": "ready", "grpc_port": app.state.grpc_port}
        except Exception:
            return JSONResponse(status_code=503, content={"detail": "Archive or Kafka unavailable"})

    return app


app = create_app()
