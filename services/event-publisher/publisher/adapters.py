import os
import threading
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from confluent_kafka import KafkaException, Producer


class Unavailable(Exception):
    pass


class Conflict(Exception):
    pass


def kafka_config():
    config = {"bootstrap.servers": os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092"),
              "socket.timeout.ms": 2000}
    mode = os.environ.get("KAFKA_AUTH_MODE", "local")
    if mode == "iam":
        from aws_msk_iam_sasl_signer import MSKAuthTokenProvider

        def token(_):
            value, expires_ms = MSKAuthTokenProvider.generate_auth_token(os.environ.get("AWS_REGION", "ap-south-1"))
            return value, expires_ms / 1000

        config.update({"security.protocol": "SASL_SSL", "sasl.mechanism": "OAUTHBEARER", "oauth_cb": token})
    elif mode != "local":
        raise ValueError("KAFKA_AUTH_MODE must be local or iam")
    return config


def archive_client():
    mode = os.environ.get("ARCHIVE_MODE", "local")
    options = {"config": Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 0},
                                 s3={"addressing_style": "path"}, proxies={}),
               "region_name": os.environ.get("AWS_REGION", "ap-south-1")}
    if mode == "local":
        access = os.environ.get("ARCHIVE_LOCAL_ACCESS_KEY")
        secret = os.environ.get("ARCHIVE_LOCAL_SECRET_KEY")
        if not access or not secret:
            raise Unavailable("Local archive credentials not configured")
        options.update(endpoint_url=os.environ.get("ARCHIVE_ENDPOINT_URL", "http://127.0.0.1:8333"),
                       aws_access_key_id=access, aws_secret_access_key=secret)
    elif mode != "aws":
        raise ValueError("ARCHIVE_MODE must be local or aws")
    # AWS mode deliberately uses the default workload credential chain and HTTPS endpoint.
    return boto3.client("s3", **options)


class S3Archive:
    def __init__(self, client=None, bucket=None):
        self.client = client or archive_client()
        self.bucket = bucket or os.environ.get("ARCHIVE_BUCKET", "traffic-archive")

    def read(self, key):
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        try:
            return body.read()
        finally:
            body.close()

    def ensure(self, key, payload):
        # Caller serializes all attempts in the single active publisher process.
        try:
            existing = self.read(key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") not in ("NoSuchKey", "404"):
                raise Unavailable("Archive read unavailable") from error
            try:
                self.client.put_object(Bucket=self.bucket, Key=key, Body=payload, ContentType="application/json")
            except (BotoCoreError, ClientError) as failure:
                raise Unavailable("Archive write unavailable") from failure
        except BotoCoreError as error:
            raise Unavailable("Archive read unavailable") from error
        else:
            if existing != payload:
                raise Conflict("Event ID already has different archived content")

    def ready(self):
        self.client.head_bucket(Bucket=self.bucket)

    def close(self):
        self.client.close()


class KafkaSink:
    def __init__(self, producer=None, topic=None):
        self.topic = topic or os.environ.get("KAFKA_RAW_TOPIC", "traffic.raw")
        self.producer = producer or Producer({**kafka_config(), "enable.idempotence": True,
                                              "acks": "all", "delivery.timeout.ms": 10000,
                                              "request.timeout.ms": 3000})

    def publish(self, key, payload):
        complete = threading.Event()
        result = []

        def delivered(error, message):
            result.append(error)
            complete.set()

        try:
            self.producer.produce(self.topic, key=key.encode("utf-8"), value=payload, on_delivery=delivered)
            deadline = time.monotonic() + 10.5
            while not complete.is_set() and time.monotonic() < deadline:
                self.producer.poll(0.1)
        except (KafkaException, BufferError) as error:
            raise Unavailable("Kafka publication unavailable") from error
        if not complete.is_set() or result[0] is not None:
            raise Unavailable("Kafka acknowledgement unavailable; retry the same event ID")

    def ready(self):
        metadata = self.producer.list_topics(self.topic, timeout=2)
        if self.topic not in metadata.topics or metadata.topics[self.topic].error:
            raise Unavailable("Kafka input topic unavailable")

    def close(self):
        self.producer.flush(2)
