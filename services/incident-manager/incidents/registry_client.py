from urllib.parse import quote

import httpx
from fastapi import HTTPException


class RegistryClient:
    def __init__(self, base_url, transport=None):
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=2.0,
                                   transport=transport, trust_env=False, follow_redirects=False)

    def validate_intersection(self, identifier):
        try:
            response = self.client.get(f"/intersections/{quote(identifier, safe='')}")
            if response.status_code == 404:
                raise HTTPException(422, "Unknown intersection reference")
            if response.status_code != 200:
                raise HTTPException(503, "Sensor Registry unavailable")
            data = response.json()
            if not isinstance(data, dict) or data.get("intersection_id") != identifier:
                raise HTTPException(503, "Invalid Sensor Registry response")
        except (httpx.HTTPError, ValueError) as error:
            raise HTTPException(503, "Sensor Registry unavailable") from error

    def close(self):
        self.client.close()
