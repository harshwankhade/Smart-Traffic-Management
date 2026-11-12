"""Opt-in ZooKeeper election for local Event Publisher replicas."""
import logging
import json
from datetime import datetime, timezone
import os
import socket
import threading
import time

LOG = logging.getLogger("event-publisher.coordination")


def enabled_from_environment():
    return os.environ.get("PUBLISHER_ZOOKEEPER_ENABLED", "0") == "1"


class ZooKeeperElection:
    """Elect the lowest ephemeral-sequential participant as the active publisher."""

    def __init__(self, hosts=None, instance_id=None, root=None, client_factory=None,
                 grpc_target=None, http_url=None, reporter=None):
        self.hosts = hosts or os.environ.get("PUBLISHER_ZOOKEEPER_HOSTS", "127.0.0.1:2181")
        self.instance_id = instance_id or os.environ.get(
            "PUBLISHER_INSTANCE_ID", f"{socket.gethostname()}-{os.getpid()}")
        self.root = root or os.environ.get("PUBLISHER_ZOOKEEPER_ROOT", "/smarttraffic/publishers")
        self.grpc_target = grpc_target or os.environ.get(
            "PUBLISHER_ADVERTISED_GRPC_TARGET", os.environ.get("PUBLISHER_GRPC_BIND", "127.0.0.1:50051"))
        self.http_url = http_url or os.environ.get("PUBLISHER_ADVERTISED_HTTP_URL", "http://127.0.0.1:8003")
        self._client_factory = client_factory or self._kazoo_client
        self._client = None
        self._node = None
        self._connected = False
        self._leader = False
        self._stopped = False
        self._replacing = False
        self._wake = threading.Event()
        self._monitor_started = False
        self._suspended_since = None
        self.reporter = reporter
        self._metrics = {"events_emitted": 0, "report_failures": 0, "leader_transitions": 0}
        self._lock = threading.RLock()

    @staticmethod
    def _kazoo_client(hosts):
        try:
            from kazoo.client import KazooClient
        except ImportError as error:
            raise RuntimeError("ZooKeeper coordination requires kazoo; install requirements-lock.txt") from error
        return KazooClient(hosts=hosts, timeout=4)

    def start(self):
        with self._lock:
            self._stopped = False
            self._wake.clear()
            if not self._monitor_started:
                self._monitor_started = True
                threading.Thread(target=self._monitor_membership, daemon=True).start()
        self._new_session()

    def _monitor_membership(self):
        """Detect an elected leader's vanished ephemeral node after local server reset."""
        while True:
            self._wake.wait(1)
            self._wake.clear()
            with self._lock:
                if self._stopped:
                    return
                connected, replacing = self._connected, self._replacing
                suspended_since = self._suspended_since
            if connected and not replacing:
                self._refresh()
            elif suspended_since is not None and not replacing and time.monotonic() - suspended_since >= 5:
                self._on_state("LOST")

    def _new_session(self):
        client = self._client_factory(self.hosts)
        client.add_listener(self._on_state)
        client.start(timeout=5)
        client.ensure_path(self.root)
        payload = json.dumps({"instance_id": self.instance_id, "grpc_target": self.grpc_target,
                              "http_url": self.http_url}, sort_keys=True).encode("utf-8")
        node = client.create(f"{self.root}/publisher-", payload,
                             ephemeral=True, sequence=True)
        with self._lock:
            if self._stopped:
                client.stop()
                client.close()
                return
            self._client, self._node, self._connected = client, node, True
            self._suspended_since = None
            rejoined = self._metrics["events_emitted"] > 0
        self._refresh()
        if rejoined:
            self._emit("session_rejoined", False)
        LOG.info("ZooKeeper participant joined instance_id=%s node=%s", self.instance_id, node)

    def _on_state(self, state):
        name = getattr(state, "name", str(state)).upper()
        if name == "CONNECTED":
            with self._lock:
                self._connected = True
                self._suspended_since = None
            self._refresh()
        elif name in ("SUSPENDED", "LOST"):
            with self._lock:
                was_leader, self._connected, self._leader = self._leader, False, False
                if name == "SUSPENDED" and self._suspended_since is None:
                    self._suspended_since = time.monotonic()
                elif name == "LOST":
                    self._suspended_since = None
            if was_leader:
                self._emit("leader_lost", False)
            self._emit("session_suspended" if name == "SUSPENDED" else "session_lost", False)
            LOG.warning("ZooKeeper session %s; publisher is not ready", name.lower())
            if name == "LOST":
                threading.Thread(target=self._replace_lost_session, daemon=True).start()

    def _replace_lost_session(self):
        with self._lock:
            if self._stopped or self._replacing:
                return
            self._replacing = True
            old, self._client, self._node = self._client, None, None
        if old:
            try:
                old.stop()
                old.close()
            except Exception:
                LOG.warning("Unable to close expired ZooKeeper session", exc_info=True)
        try:
            while True:
                with self._lock:
                    if self._stopped:
                        return
                try:
                    self._new_session()
                    return
                except Exception:
                    LOG.warning("Unable to establish fresh ZooKeeper session; retrying", exc_info=True)
                    self._wake.wait(1)
                    self._wake.clear()
        finally:
            with self._lock:
                self._replacing = False

    def _refresh(self, *_):
        with self._lock:
            client, node, connected = self._client, self._node, self._connected
        if not client or not node or not connected:
            return
        try:
            mine = node.rsplit("/", 1)[1]
            while True:
                children = sorted(client.get_children(self.root))
                position = children.index(mine)
                leader = position == 0
                if leader:
                    break
                predecessor = children[position - 1]
                if client.exists(f"{self.root}/{predecessor}", watch=self._refresh):
                    break
            with self._lock:
                was_leader = self._leader
                self._leader = leader and self._connected and self._node == node
                changed = was_leader != self._leader
                if changed:
                    self._metrics["leader_transitions"] += 1
            if changed:
                self._emit("leader_elected" if leader else "leader_lost", leader)
            LOG.info("ZooKeeper election instance_id=%s leader=%s", self.instance_id, leader)
        except ValueError:
            # A restarted ZooKeeper server no longer knows this ephemeral node. Treat that
            # missing membership as session loss and join with a fresh session/node.
            with self._lock:
                self._connected = self._leader = False
            LOG.warning("ZooKeeper election node disappeared; publisher is not ready")
            self._on_state("LOST")
        except Exception as error:
            if error.__class__.__name__ == "NoNodeError":
                # A fresh local ZooKeeper server also lacks the election root itself.
                with self._lock:
                    self._connected = self._leader = False
                LOG.warning("ZooKeeper election path disappeared; publisher is not ready")
                self._on_state("LOST")
                return
            with self._lock:
                self._leader = False
            LOG.warning("Unable to refresh ZooKeeper election; publisher is not ready", exc_info=True)

    def ready(self):
        with self._lock:
            return self._connected and self._leader

    def _emit(self, event_type, leader):
        with self._lock:
            session_id = (self._node or "unknown").rsplit("/", 1)[-1]
            event = {"schema_version": "1.0", "publisher_id": self.instance_id, "session_id": session_id,
                     "event_type": event_type,
                     "recovery_id": f"{self.instance_id}/{session_id}/{event_type}/v1",
                     "occurred_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                     "leader": leader}
            self._metrics["events_emitted"] += 1
        LOG.info("publisher recovery event=%s recovery_id=%s leader=%s", event_type, event["recovery_id"], leader)
        if self.reporter:
            try:
                self.reporter.report(event)
            except Exception:
                with self._lock:
                    self._metrics["report_failures"] += 1
                LOG.warning("Unable to persist recovery event=%s", event["recovery_id"], exc_info=True)

    def status(self):
        with self._lock:
            return {"enabled": True, "instance_id": self.instance_id, "node": self._node,
                    "leader": self._leader, "ready": self._connected and self._leader,
                    "grpc_target": self.grpc_target, "http_url": self.http_url,
                    "metrics": dict(self._metrics)}

    def stop(self):
        with self._lock:
            self._stopped = True
            self._wake.set()
            client, self._client = self._client, None
            self._node = None
            self._connected = self._leader = False
            self._suspended_since = None
        if client:
            client.stop()
            client.close()


class SinglePublisher:
    """Compatibility mode used unless ZooKeeper is explicitly enabled."""

    def start(self):
        pass

    def ready(self):
        return True

    def status(self):
        return {"enabled": False, "leader": True, "ready": True}

    def stop(self):
        pass
