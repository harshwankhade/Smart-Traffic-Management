from urllib.parse import quote

import grpc
import httpx
from fastapi import HTTPException

from traffic_contracts import publisher_pb2_grpc


class RegistryClient:
    def __init__(self, base_url, transport=None):
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=2,
                                   transport=transport, trust_env=False, follow_redirects=False)

    def validate(self, reading):
        try:
            response = self.client.get(f"/sensors/{quote(reading.sensor_id, safe='')}")
            if response.status_code == 404:
                raise HTTPException(422, "Unknown sensor reference")
            if response.status_code != 200:
                raise HTTPException(503, "Sensor Registry unavailable")
            sensor = response.json()
            if not isinstance(sensor, dict) or sensor.get("sensor_id") != reading.sensor_id or sensor.get("status") not in ("active", "inactive"):
                raise HTTPException(503, "Invalid Registry response")
            if sensor["status"] != "active" or sensor.get("intersection_id") != reading.intersection_id:
                raise HTTPException(422, "Sensor must be active and match its registered intersection")
        except (httpx.HTTPError, ValueError) as error:
            raise HTTPException(503, "Sensor Registry unavailable") from error

    def ready(self):
        if self.client.get("/healthz").status_code != 200:
            raise RuntimeError("Registry unavailable")

    def close(self):
        self.client.close()


class PublisherClient:
    def __init__(self, target, health_url="http://127.0.0.1:8003"):
        self.channel = grpc.insecure_channel(target, options=[("grpc.enable_retries", 0)])
        self.stub = publisher_pb2_grpc.EventPublisherStub(self.channel)
        self.health = httpx.Client(base_url=health_url, timeout=2, trust_env=False)

    def publish(self, reading):
        try:
            receipt = self.stub.PublishReading(reading.to_proto(), timeout=15)
        except grpc.RpcError as error:
            status = {grpc.StatusCode.INVALID_ARGUMENT: 422, grpc.StatusCode.ALREADY_EXISTS: 409,
                      grpc.StatusCode.UNAVAILABLE: 503, grpc.StatusCode.DEADLINE_EXCEEDED: 503}.get(error.code(), 500)
            raise HTTPException(status, "Publisher rejected input" if status == 422 else
                                "Event ID conflicts with archived content" if status == 409 else
                                "Publisher unavailable; retry the same event ID" if status == 503 else
                                "Unexpected publisher failure") from error
        if not receipt.accepted or receipt.event_id != reading.event_id:
            raise HTTPException(500, "Invalid publisher acknowledgement")

    def ready(self):
        grpc.channel_ready_future(self.channel).result(timeout=2)
        if self.health.get("/readyz").status_code != 200:
            raise RuntimeError("Publisher sinks unavailable")

    def close(self):
        self.channel.close()
        self.health.close()
