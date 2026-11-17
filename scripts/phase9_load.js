import http from "k6/http";
import { check, sleep } from "k6";

const baseUrl = __ENV.BASE_URL;
const registryUrl = __ENV.REGISTRY_URL || baseUrl;
const ingestionUrl = __ENV.INGESTION_URL || baseUrl;
const analyticsUrl = __ENV.ANALYTICS_URL || baseUrl;
const runId = __ENV.RUN_ID;
const intersectionId = __ENV.INTERSECTION_ID || `p9-${runId}-intersection`;
const sensorId = __ENV.SENSOR_ID || `p9-${runId}-sensor`;

if ((!baseUrl && (!registryUrl || !ingestionUrl || !analyticsUrl)) || !runId) {
  throw new Error("Set BASE_URL or all internal service URLs, plus a unique RUN_ID.");
}

export const options = {
  scenarios: {
    ingestion: {
      executor: "ramping-vus",
      exec: "submitReading",
      startVUs: 0,
      stages: [
        { duration: "1m", target: 80 },
        { duration: "4m", target: 160 },
        { duration: "1m", target: 0 },
      ],
    },
    analytics: {
      executor: "constant-vus",
      exec: "readSummaries",
      vus: 40,
      duration: "6m",
      startTime: "30s",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<2000"],
  },
};

export function setup() {
  const headers = { headers: { "Content-Type": "application/json" } };
  const intersection = http.post(`${registryUrl}/intersections`, JSON.stringify({
    intersection_id: intersectionId, name: `Phase 9 ${runId}`, location: "Synthetic load lane",
  }), headers);
  check(intersection, { "intersection registered": (r) => r.status === 201 || r.status === 409 });
  const sensor = http.post(`${registryUrl}/sensors`, JSON.stringify({
    sensor_id: sensorId, intersection_id: intersectionId, location: "Synthetic load lane", status: "active",
  }), headers);
  check(sensor, { "sensor registered": (r) => r.status === 201 || r.status === 409 });
  return { intersectionId, sensorId };
}

export function submitReading(data) {
  const eventId = `${runId}-${__VU}-${__ITER}`;
  const response = http.post(`${ingestionUrl}/readings`, JSON.stringify({
    schema_version: "1.0", event_id: eventId, sensor_id: data.sensorId,
    intersection_id: data.intersectionId, observed_at: new Date().toISOString(),
    vehicle_count: 40, average_speed: 18.5, occupancy: 0.82,
  }), { headers: { "Content-Type": "application/json" } });
  check(response, { "reading accepted": (r) => r.status === 202 });
  sleep(0.1);
}

export function readSummaries(data) {
  const response = http.get(`${analyticsUrl}/traffic/summaries?intersection_id=${encodeURIComponent(data.intersectionId)}&limit=50`);
  check(response, { "analytics query succeeded": (r) => r.status === 200 });
  sleep(0.15);
}
