"""Opt-in local Docker check of the GitOps broker's TLS and persistence settings.

Uses an isolated container and temporary certificate under .data; stops/removes
only that container in finally. Requires Docker, OpenSSL and project dependencies.
"""
import argparse
from pathlib import Path
import socket
import subprocess
import textwrap
import time
import uuid

from confluent_kafka import Consumer, Producer

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openssl", default="openssl")
    args = parser.parse_args()
    name = "smarttraffic-kafka-check-" + uuid.uuid4().hex[:10]
    directory = ROOT / ".data" / name
    directory.mkdir(parents=True)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    def run(*command, capture=False):
        result = subprocess.run(command, cwd=directory, text=True, capture_output=capture)
        if result.returncode:
            if capture:
                print(result.stdout or "")
                print(result.stderr or "")
            result.check_returncode()
        return result.stdout
    run(args.openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", "tls.key", "-out", "tls.crt", "-days", "1", "-subj", "/CN=localhost",
        "-addext", "subjectAltName=DNS:localhost", capture=True)
    # OpenSSL 3 writes unencrypted PKCS8, matching the Terraform TLS secret.
    manifest = (ROOT / "deploy/gitops/apps/kafka.yaml").read_text(encoding="utf-8")
    for field, following in [("server.properties", "client.properties"),
                             ("client.properties", "bootstrap-topics.sh")]:
        block = manifest.split(f"  {field}: |\n", 1)[1].split(f"  {following}: |\n", 1)[0]
        value = textwrap.dedent(block).replace("kafka.smarttraffic.internal", "localhost")
        value = value.replace(":9093", f":{port}")
        (directory / field).write_text(value, encoding="utf-8", newline="\n")
    block = manifest.split("  bootstrap-topics.sh: |\n", 1)[1].split("---", 1)[0]
    (directory / "bootstrap-topics.sh").write_text(textwrap.dedent(block).replace(":9093", f":{port}"), encoding="utf-8", newline="\n")
    command = manifest.split("              cat /tls/tls.key", 1)[1].split("          env:", 1)[0]
    command = textwrap.dedent("              cat /tls/tls.key" + command)
    started = False
    try:
        run("docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:{port}",
            "-v", f"{directory}:/config:ro", "-v", f"{directory}:/tls:ro",
            "--tmpfs", "/work:uid=1000,gid=1000", "-e", "KAFKA_HEAP_OPTS=-Xms256m -Xmx512m",
            "apache/kafka:3.9.1", "/bin/bash", "-ec", command, capture=True)
        started = True
        run("docker", "exec", name, "/bin/bash", "/config/bootstrap-topics.sh", capture=True)
        config = {"bootstrap.servers": f"localhost:{port}", "security.protocol": "SSL",
                  "ssl.ca.location": str(directory / "tls.crt"),
                  "ssl.endpoint.identification.algorithm": "https"}
        delivered = []
        producer = Producer({**config, "acks": "all", "enable.idempotence": True})
        producer.produce("traffic.raw", key="tls-test", value=name,
                         on_delivery=lambda error, message: delivered.append(error))
        if producer.flush(20) or delivered != [None]:
            raise RuntimeError("TLS Kafka write did not receive acknowledgement")
        run("docker", "restart", name, capture=True)
        # Restart preserves the broker data and formatted cluster identity.
        run("docker", "exec", name, "/bin/bash", "/config/bootstrap-topics.sh", capture=True)
        consumer = Consumer({**config, "group.id": name, "auto.offset.reset": "earliest",
                             "enable.auto.commit": False})
        try:
            consumer.subscribe(["traffic.raw"])
            deadline = time.monotonic() + 30
            found = False
            while time.monotonic() < deadline:
                message = consumer.poll(1)
                if message and not message.error() and message.value().decode() == name:
                    found = True
                    break
            if not found:
                raise RuntimeError("Persisted TLS Kafka record missing after restart")
        finally:
            consumer.close()
        print("PASS: private broker settings, both topics, TLS producer acknowledgement, restart persistence and TLS consumer read")
    except Exception:
        if started:
            # Broker logs contain no certificate private key or request body.
            subprocess.run(["docker", "logs", "--tail", "35", name], check=False)
        raise
    finally:
        if started:
            run("docker", "rm", "-f", name, capture=True)
        # No recursive deletion: retain non-secret configs as local evidence.
        for filename in ("tls.key", "tls.crt"):
            (directory / filename).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
