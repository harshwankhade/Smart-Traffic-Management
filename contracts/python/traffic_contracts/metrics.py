"""Small dependency-free Prometheus exporter for the six HTTP services."""

from collections import Counter, defaultdict
from threading import Lock
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse


_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


def _labels(values):
    def escape(value):
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    return ",".join(f'{key}="{escape(value)}"' for key, value in values.items())


class HttpMetrics:
    def __init__(self, service):
        self.service = service
        self.lock = Lock()
        self.requests = Counter()
        self.duration_sum = defaultdict(float)
        self.duration_count = Counter()
        self.duration_buckets = Counter()
        self.inflight = 0

    def observe(self, method, route, status, duration):
        key = (method, route, str(status))
        with self.lock:
            self.requests[key] += 1
            self.duration_sum[key] += duration
            self.duration_count[key] += 1
            for bucket in _BUCKETS:
                if duration <= bucket:
                    self.duration_buckets[key + (bucket,)] += 1

    def render(self):
        with self.lock:
            lines = [
                "# HELP smarttraffic_http_requests_total HTTP responses completed by the service.",
                "# TYPE smarttraffic_http_requests_total counter",
            ]
            for (method, route, status), value in sorted(self.requests.items()):
                labels = _labels({"service": self.service, "method": method, "route": route, "status": status})
                lines.append(f"smarttraffic_http_requests_total{{{labels}}} {value}")
            lines.extend([
                "# HELP smarttraffic_http_request_duration_seconds HTTP request duration in seconds.",
                "# TYPE smarttraffic_http_request_duration_seconds histogram",
            ])
            for key, count in sorted(self.duration_count.items()):
                method, route, status = key
                base = {"service": self.service, "method": method, "route": route, "status": status}
                for bucket in _BUCKETS:
                    labels = _labels({**base, "le": bucket})
                    lines.append(f"smarttraffic_http_request_duration_seconds_bucket{{{labels}}} {self.duration_buckets[key + (bucket,)]}")
                labels = _labels({**base, "le": "+Inf"})
                lines.append(f"smarttraffic_http_request_duration_seconds_bucket{{{labels}}} {count}")
                labels = _labels(base)
                lines.append(f"smarttraffic_http_request_duration_seconds_sum{{{labels}}} {self.duration_sum[key]:.9f}")
                lines.append(f"smarttraffic_http_request_duration_seconds_count{{{labels}}} {count}")
            lines.extend([
                "# HELP smarttraffic_http_inflight_requests Requests currently executing.",
                "# TYPE smarttraffic_http_inflight_requests gauge",
                f'smarttraffic_http_inflight_requests{{{_labels({"service": self.service})}}} {self.inflight}',
            ])
            return "\n".join(lines) + "\n"


def install_http_metrics(app: FastAPI, service: str):
    """Expose ``/metrics`` and instrument non-metrics HTTP requests.

    Dynamic identifiers are replaced by FastAPI's route template, preventing
    unbounded time-series cardinality from event, sensor or incident IDs.
    """
    metrics = HttpMetrics(service)
    app.state.http_metrics = metrics

    @app.middleware("http")
    async def collect(request: Request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)
        route = request.url.path
        for candidate in request.app.routes:
            matcher = getattr(candidate, "matches", None)
            if matcher and matcher(request.scope)[0].value == 2:
                route = candidate.path
                break
        started = perf_counter()
        with metrics.lock:
            metrics.inflight += 1
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            status = 500
            raise
        finally:
            elapsed = perf_counter() - started
            with metrics.lock:
                metrics.inflight -= 1
            metrics.observe(request.method, route, status, elapsed)
        return response

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics():
        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4; charset=utf-8")
