package com.smarttraffic;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Set;

/** Strict Kafka-boundary validation independent of Registry availability. */
public class Reading implements Serializable {
    public String eventId, intersectionId, fingerprint;
    public long timestamp;
    public java.math.BigInteger count;
    public BigDecimal speed, occupancy;
    public Reading() {}
    public static Reading parse(String json) throws Exception {
        JsonNode n = new ObjectMapper().readTree(json);
        Set<String> fields = Set.of("schema_version", "event_id", "sensor_id", "intersection_id", "observed_at", "vehicle_count", "average_speed", "occupancy");
        if (!n.isObject()) throw new IllegalArgumentException("reading must be an object");
        n.fieldNames().forEachRemaining(k -> { if (!fields.contains(k)) throw new IllegalArgumentException("unknown field"); });
        if (!n.path("schema_version").isTextual() || !"1.0".equals(n.path("schema_version").asText())) throw new IllegalArgumentException("schema version");
        for (String k : Set.of("event_id", "sensor_id", "intersection_id", "observed_at")) {
            if (!n.path(k).isTextual() || n.path(k).asText().isBlank() || (!k.equals("observed_at") && n.path(k).asText().length() > 128)) throw new IllegalArgumentException("invalid " + k);
        }
        String observed = n.get("observed_at").asText();
        if (!observed.endsWith("Z")) throw new IllegalArgumentException("UTC required");
        Reading r = new Reading();
        r.eventId = n.get("event_id").asText(); r.intersectionId = n.get("intersection_id").asText();
        // Publisher preserves sub-nanosecond fractional digits; event-time windows use milliseconds.
        String clock = observed.replaceFirst("(\\.\\d{9})\\d+Z$", "$1Z");
        r.timestamp = Instant.parse(clock).toEpochMilli();
        if (n.has("vehicle_count")) {
            JsonNode c = n.get("vehicle_count");
            if (!c.isIntegralNumber() || !c.canConvertToLong() || c.longValue() < 0) throw new IllegalArgumentException("invalid count");
            r.count = c.bigIntegerValue();
        }
        r.speed = measure(n, "average_speed"); r.occupancy = measure(n, "occupancy");
        if (r.occupancy != null && r.occupancy.compareTo(BigDecimal.ONE) > 0) throw new IllegalArgumentException("occupancy");
        if (r.count == null && r.speed == null && r.occupancy == null) throw new IllegalArgumentException("measurement required");
        // Canonical publisher bytes are stable, but tolerate JSON field reordering.
        java.util.TreeMap<String, Object> canonical = new java.util.TreeMap<>();
        n.fields().forEachRemaining(e -> canonical.put(e.getKey(), e.getValue()));
        r.fingerprint = new ObjectMapper().writeValueAsString(canonical);
        return r;
    }
    private static BigDecimal measure(JsonNode n, String k) {
        if (!n.has(k)) return null;
        JsonNode v = n.get(k);
        if (!v.isNumber() || !Double.isFinite(v.doubleValue()) || v.decimalValue().signum() < 0) throw new IllegalArgumentException("invalid " + k);
        return v.decimalValue();
    }
}
