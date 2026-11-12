import json
import os
import time
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


class ZooKeeperPublisherClient:
    """Resolve the elected publisher for every bounded retry using ZooKeeper."""

    def __init__(self, hosts=None, root=None, attempts=None, delay_seconds=None, client_factory=None,
                 publisher_factory=PublisherClient, sleeper=time.sleep):
        self.hosts = hosts or os.environ.get("PUBLISHER_ZOOKEEPER_HOSTS", "127.0.0.1:2181")
        self.root = root or os.environ.get("PUBLISHER_ZOOKEEPER_ROOT", "/smarttraffic/publishers")
        self.attempts = attempts if attempts is not None else int(os.environ.get("PUBLISHER_FAILOVER_RETRY_ATTEMPTS", "3"))
        self.delay_seconds = delay_seconds if delay_seconds is not None else float(
            os.environ.get("PUBLISHER_FAILOVER_RETRY_DELAY_SECONDS", "0.15"))
        if not 1 <= self.attempts <= 5 or not 0 <= self.delay_seconds <= 2:
            raise ValueError("Publisher failover retries must be 1-5 with a 0-2 second delay")
        if client_factory is None:
            try:
                from kazoo.client import KazooClient
            except ImportError as error:
                raise RuntimeError("ZooKeeper publisher discovery requires kazoo; install requirements-lock.txt") from error
            client_factory = lambda hosts: KazooClient(hosts=hosts, timeout=4)
        self.client = client_factory(self.hosts)
        self.client.start(timeout=5)
        self.publisher_factory, self.sleeper = publisher_factory, sleeper

    def _active_endpoint(self):
        try:
            children = sorted(self.client.get_children(self.root))
            if not children:
                raise RuntimeError("No active publisher elected")
            raw, _ = self.client.get(f"{self.root}/{children[0]}")
            value = json.loads(raw.decode("utf-8"))
            target, health_url = value["grpc_target"], value["http_url"]
            if not isinstance(target, str) or not isinstance(health_url, str):
                raise ValueError("Invalid publisher endpoint")
            return target, health_url
        except (KeyError, TypeError, UnicodeDecodeError, ValueError) as error:
            raise RuntimeError("Invalid elected publisher record") from error
        except Exception as error:
            raise RuntimeError("Active publisher discovery unavailable") from error

    def _with_active_publisher(self, operation):
        target, health_url = self._active_endpoint()
        publisher = self.publisher_factory(target, health_url)
        try:
            return operation(publisher)
        finally:
            publisher.close()

    def publish(self, reading):
        last_error = None
        for attempt in range(self.attempts):
            try:
                return self._with_active_publisher(lambda publisher: publisher.publish(reading))
            except HTTPException as error:
                if error.status_code != 503:
                    raise
                last_error = error
            except Exception as error:
                last_error = error
            if attempt + 1 < self.attempts:
                self.sleeper(self.delay_seconds)
        raise HTTPException(503, "Publisher unavailable during leader change; retry the same event ID") from last_error

    def ready(self):
        self._with_active_publisher(lambda publisher: publisher.ready())

    def close(self):
        self.client.stop()
        self.client.close()
