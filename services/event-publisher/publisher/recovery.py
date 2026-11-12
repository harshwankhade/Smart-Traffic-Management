"""Best-effort reporting of publisher recovery events to Traffic Analytics."""
import httpx


class HttpRecoveryReporter:
    def __init__(self, base_url):
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=1, trust_env=False)

    def report(self, event):
        response = self.client.post("/internal/recovery-events", json=event)
        if response.status_code not in (200, 202):
            raise RuntimeError(f"Traffic Analytics rejected recovery event: {response.status_code}")

    def close(self):
        self.client.close()
