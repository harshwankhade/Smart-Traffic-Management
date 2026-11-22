"""Explicit trust configuration for the private demo broker."""
import os


def tls_config():
    certificate = os.environ.get("KAFKA_SSL_CA_PEM", "").strip()
    if "-----BEGIN CERTIFICATE-----" not in certificate:
        raise ValueError("tls mode requires KAFKA_SSL_CA_PEM")
    return {"security.protocol": "SSL", "ssl.ca.pem": certificate,
            "enable.ssl.certificate.verification": True,
            "ssl.endpoint.identification.algorithm": "https"}
