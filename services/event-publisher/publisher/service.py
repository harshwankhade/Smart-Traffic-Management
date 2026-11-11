import logging
import threading

import grpc
from pydantic import ValidationError

from traffic_contracts import publisher_pb2, publisher_pb2_grpc
from traffic_contracts.reading import Reading, archive_key
from .adapters import Conflict, Unavailable

LOG = logging.getLogger("event-publisher")


class Publisher(publisher_pb2_grpc.EventPublisherServicer):
    def __init__(self, archive, sink):
        self.archive, self.sink = archive, sink
        self.lock = threading.Lock()

    def PublishReading(self, request, context):
        try:
            reading = Reading.from_proto(request)
        except (ValidationError, ValueError):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid v1 reading")
        timeout = min(context.time_remaining() or 15, 15)
        if not self.lock.acquire(timeout=max(timeout, 0)):
            context.abort(grpc.StatusCode.UNAVAILABLE, "Publisher busy; retry same event ID")
        try:
            if not context.is_active():
                raise Unavailable("Request deadline elapsed")
            self.archive.ensure(archive_key(reading.event_id), reading.canonical())
            if not context.is_active():
                raise Unavailable("Request deadline elapsed after archival")
            self.sink.publish(reading.intersection_id, reading.canonical())
            LOG.info("publication acknowledged event_id=%r", reading.event_id)
            return publisher_pb2.PublishReceipt(event_id=reading.event_id, accepted=True)
        except Conflict:
            context.abort(grpc.StatusCode.ALREADY_EXISTS, "Event ID reused with different content")
        except Unavailable:
            LOG.warning("publication incomplete event_id=%r", reading.event_id)
            context.abort(grpc.StatusCode.UNAVAILABLE, "Archive or Kafka unavailable; retry same event ID")
        except Exception:
            LOG.error("unexpected publication failure event_id=%r", reading.event_id)
            context.abort(grpc.StatusCode.INTERNAL, "Unexpected publisher failure")
        finally:
            self.lock.release()
