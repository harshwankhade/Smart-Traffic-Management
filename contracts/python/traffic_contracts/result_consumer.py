"""Kafka result consumer: validate, persist, then synchronously commit offsets."""

import json
import logging
import os
import threading
from decimal import Decimal

from confluent_kafka import Consumer

from traffic_contracts.dynamo_store import RecordConflict
from traffic_contracts.result import validate_result

LOG = logging.getLogger(__name__)


def _reject_constant(value):
    raise ValueError(f"non-JSON numeric constant {value}")


def kafka_config(group_id):
    prefix = os.getenv("PHASE5_CONSUMER_GROUP_PREFIX", "")
    offset_reset = os.getenv("PHASE5_KAFKA_OFFSET_RESET", "earliest")
    if offset_reset not in ("earliest", "latest"):
        raise ValueError("PHASE5_KAFKA_OFFSET_RESET must be earliest or latest")
    config = {"bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092"),
              "group.id": prefix + group_id,
              "enable.auto.commit": False, "enable.auto.offset.store": False,
              "auto.offset.reset": offset_reset, "socket.timeout.ms": 2000}
    mode = os.getenv("KAFKA_AUTH_MODE", "local")
    if mode == "iam":
        from aws_msk_iam_sasl_signer import MSKAuthTokenProvider

        def token(_):
            value, expires_ms = MSKAuthTokenProvider.generate_auth_token(
                os.getenv("AWS_REGION", "ap-south-1"))
            return value, expires_ms / 1000

        config.update({"security.protocol": "SASL_SSL", "sasl.mechanism": "OAUTHBEARER",
                       "oauth_cb": token})
    elif mode != "local":
        raise ValueError("KAFKA_AUTH_MODE must be local or iam")
    return config


class ResultConsumer:
    def __init__(self, group_id, store, persist, *, consumer_factory=Consumer):
        self.topic = os.getenv("KAFKA_RESULTS_TOPIC", "traffic.results")
        self.store = store
        self.persist = persist
        self.consumer_factory = consumer_factory
        self.config = kafka_config(group_id)
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = threading.Lock()
        self.connected = False
        self.blocked = None
        self.counts = {"persisted": 0, "duplicates": 0, "invalid": 0,
                       "committed": 0, "retry": 0}

    def start(self):
        if self.thread is not None:
            raise RuntimeError("consumer already started")
        self.thread = threading.Thread(target=self._run, name=self.config["group.id"], daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=10)

    def snapshot(self):
        with self.lock:
            return {"connected": self.connected, "blocked": self.blocked,
                    "counts": dict(self.counts), "running": bool(self.thread and self.thread.is_alive())}

    def ready(self):
        state = self.snapshot()
        if not state["running"] or not state["connected"] or state["blocked"]:
            return False
        try:
            self.store.ready()
            return True
        except Exception:
            return False

    def _set_connected(self, value):
        with self.lock:
            self.connected = value

    def _count(self, name):
        with self.lock:
            self.counts[name] += 1

    def _run(self):
        consumer = None
        try:
            consumer = self.consumer_factory(self.config)
            delay = 0.5
            while not self.stop_event.is_set():
                try:
                    metadata = consumer.list_topics(self.topic, timeout=3)
                    if self.topic not in metadata.topics or metadata.topics[self.topic].error:
                        raise RuntimeError("results topic unavailable")
                    break
                except Exception as exc:
                    LOG.warning("results topic unavailable: %s", type(exc).__name__)
                    self.stop_event.wait(delay)
                    delay = min(delay * 2, 5)
            if self.stop_event.is_set():
                return
            consumer.subscribe([self.topic])
            while not self.stop_event.is_set():
                message = consumer.poll(0.5)
                if message is None:
                    if not self.snapshot()["connected"] and consumer.assignment():
                        try:
                            consumer.list_topics(self.topic, timeout=2)
                            self._set_connected(True)
                        except Exception:
                            pass
                    continue
                if message.error():
                    self._set_connected(False)
                    LOG.warning("result poll failed: %s", message.error())
                    self.stop_event.wait(1)
                    continue
                self._set_connected(True)
                if not self._handle(consumer, message):
                    break
        except Exception as exc:
            LOG.exception("result consumer stopped: %s", type(exc).__name__)
        finally:
            self._set_connected(False)
            if consumer is not None:
                consumer.close()

    def _handle(self, consumer, message):
        location = "%s/%s/%s" % (message.topic(), message.partition(), message.offset())
        try:
            raw = json.loads(message.value().decode("utf-8"), parse_float=Decimal,
                             parse_constant=_reject_constant)
            result = validate_result(raw)
        except (ValueError, UnicodeError, TypeError, AttributeError) as exc:
            LOG.warning("invalid result at %s: %s", location, type(exc).__name__)
            self._count("invalid")
            return self._commit_with_retry(consumer, message, location)
        delay = 0.5
        while not self.stop_event.is_set():
            try:
                outcome = self.persist(result)
                self._count("duplicates" if outcome == "unchanged" else "persisted")
                return self._commit_with_retry(consumer, message, location)
            except RecordConflict:
                LOG.error("conflicting result quarantined at %s window_id=%s", location,
                          result["window_id"])
                with self.lock:
                    self.blocked = location
                return False
            except ValueError as exc:
                LOG.warning("invalid result at %s: %s", location, type(exc).__name__)
                self._count("invalid")
                return self._commit_with_retry(consumer, message, location)
            except Exception as exc:
                self._set_connected(False)
                self._count("retry")
                LOG.warning("result persistence unavailable at %s: %s", location,
                            type(exc).__name__)
                self.stop_event.wait(delay)
                delay = min(delay * 2, 5)
        return False

    def _commit_with_retry(self, consumer, message, location):
        delay = 0.5
        while not self.stop_event.is_set():
            try:
                committed = consumer.commit(message=message, asynchronous=False)
                if not committed or any(partition.error for partition in committed):
                    raise RuntimeError("Kafka did not confirm the offset commit")
                self._count("committed")
                self._set_connected(True)
                return True
            except Exception as exc:
                self._set_connected(False)
                self._count("retry")
                LOG.warning("result offset commit uncertain at %s: %s", location,
                            type(exc).__name__)
                self.stop_event.wait(delay)
                delay = min(delay * 2, 5)
        return False
