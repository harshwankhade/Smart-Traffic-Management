package com.smarttraffic;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.util.CloseableIterator;
import java.util.*;

class TrafficTest {
    @Test void startsWithoutManagedServicePropertiesFile() throws Exception {
        assertNotNull(FlinkJob.applicationSettings());
        assertEquals("value", FlinkJob.applicationSettings("--TEST_SETTING", "value").getProperty("TEST_SETTING"));
        assertThrows(IllegalArgumentException.class, () -> FlinkJob.applicationSettings("--missing-value"));
    }
    @Test void managedVerificationChecksActualPayloads() throws Exception {
        var probe = new VerificationProbe("unused", "test", new java.util.Properties(), 1);
        assertEquals("test-a", Reading.parse(probe.sample("a", "main", "00:00", "\"average_speed\":10")).eventId);
        var collector = new org.apache.flink.util.Collector<String>() {
            public void collect(String s) {}
            public void close() {}
        };
        var first = new TrafficPipeline.Summary(); first.readings = 2; first.countN = 2;
        first.count = java.math.BigInteger.valueOf(5); first.speedN = 2; first.speed = java.math.BigDecimal.valueOf(40);
        first.occupancyN = 2; first.occupancy = new java.math.BigDecimal("1.2");
        long start = java.time.Instant.parse("2026-11-10T10:00:00Z").toEpochMilli();
        probe.flatMap(TrafficPipeline.result("test-main", start, start + 60000, first), collector);
        first.readings = 3;
        assertThrows(IllegalStateException.class, () -> probe.flatMap(TrafficPipeline.result("test-main", start, start + 60000, first), collector));
        var second = new TrafficPipeline.Summary(); second.readings = 3; second.speedN = 3;
        second.speed = java.math.BigDecimal.valueOf(120);
        new VerificationProbe("unused", "test", new java.util.Properties(), 2)
            .flatMap(TrafficPipeline.result("test-main", start + 60000, start + 120000, second), collector);
    }
    @Test void checkpointReceiptRequiresBothPendingReadings() throws Exception {
        var receipt = new VerificationCheckpoint("test", "");
        assertFalse(receipt.ready());
        receipt.map(reading("test-pending", "test-main", "01:00", "\"average_speed\":45"));
        assertFalse(receipt.ready());
        receipt.notifyCheckpointComplete(1);
        receipt.map(reading("test-pending2", "test-main", "01:05", "\"average_speed\":25"));
        assertTrue(receipt.ready());
        receipt.notifyCheckpointComplete(2);
    }
    static class ImmediateWatermarks implements org.apache.flink.api.common.eventtime.WatermarkGenerator<Reading> {
        long maximum = Long.MIN_VALUE;
        public void onEvent(Reading r, long timestamp, org.apache.flink.api.common.eventtime.WatermarkOutput out) {
            maximum = Math.max(maximum, timestamp);
            out.emitWatermark(new org.apache.flink.api.common.eventtime.Watermark(maximum - 10001));
        }
        public void onPeriodicEmit(org.apache.flink.api.common.eventtime.WatermarkOutput out) {}
    }
    static String reading(String id, String intersection, String time, String measures) {
        return "{\"schema_version\":\"1.0\",\"event_id\":\"" + id + "\",\"sensor_id\":\"sensor\",\"intersection_id\":\"" + intersection + "\",\"observed_at\":\"2026-11-10T10:" + time + "Z\"," + measures + "}";
    }
    @Test void validation() throws Exception {
        Reading zero = Reading.parse(reading("a", "i", "00:00", "\"vehicle_count\":0,\"occupancy\":0"));
        assertEquals(java.math.BigInteger.ZERO, zero.count); assertNull(zero.speed);
        assertThrows(Exception.class, () -> Reading.parse(reading("a", "i", "00:00", "\"vehicle_count\":0").replace("\"schema_version\":\"1.0\"", "\"schema_version\":1.0")));
        assertEquals(Reading.parse(reading("a", "i", "00:00.123456789123", "\"vehicle_count\":0")).timestamp,
                     Reading.parse(reading("a", "i", "00:00.123", "\"vehicle_count\":0")).timestamp);
        for (String bad : List.of("\"occupancy\":null", "\"vehicle_count\":9223372036854775808", "\"occupancy\":1.1", "\"vehicle_count\":1.5", "\"average_speed\":-1", "\"extra\":1"))
            assertThrows(Exception.class, () -> Reading.parse(reading("a", "i", "00:00", bad)));
    }
    @Test void independentMeansAndThresholds() throws Exception {
        var aggregate = new TrafficPipeline.Aggregate(); var s = aggregate.createAccumulator();
        aggregate.add(Reading.parse(reading("a", "i", "00:00", "\"average_speed\":10,\"vehicle_count\":9223372036854775807")), s);
        aggregate.add(Reading.parse(reading("b", "i", "00:01", "\"average_speed\":30,\"vehicle_count\":9223372036854775807,\"occupancy\":0.8")), s);
        var result = new ObjectMapper().readTree(TrafficPipeline.result("i", 0, 60000, s));
        assertEquals(20, result.get("average_speed").intValue()); assertEquals("high", result.get("congestion").asText());
        assertEquals("18446744073709551614", result.get("vehicle_count_sum").asText());
        for (String[] example : new String[][] {{"20","medium"},{"40","low"},{"19.99","high"}}) {
            var x = aggregate.add(Reading.parse(reading("a", "i", "00:00", "\"average_speed\":" + example[0])), aggregate.createAccumulator());
            assertEquals(example[1], new ObjectMapper().readTree(TrafficPipeline.result("i", 0, 60000, x)).get("congestion").asText());
        }
        var onlyCount = aggregate.add(Reading.parse(reading("a", "i", "00:00", "\"vehicle_count\":0")), aggregate.createAccumulator());
        assertEquals("unknown", new ObjectMapper().readTree(TrafficPipeline.result("i", 0, 60000, onlyCount)).get("congestion").asText());
    }
    @Test void actualFlinkWindowsDeduplicateAndBoundaries() throws Exception {
        var env = StreamExecutionEnvironment.getExecutionEnvironment(); env.setParallelism(1);
        String a = reading("a", "i", "00:00", "\"average_speed\":10,\"vehicle_count\":2");
        var stream = TrafficPipeline.build(env.fromData(a, a,
            reading("b", "i", "00:59.999999999", "\"average_speed\":30,\"occupancy\":0.8"),
            reading("c", "i", "01:00", "\"vehicle_count\":3"),
            reading("d", "other", "00:30", "\"average_speed\":50")));
        List<com.fasterxml.jackson.databind.JsonNode> values = new ArrayList<>();
        try (CloseableIterator<String> it = stream.executeAndCollect()) { while (it.hasNext()) values.add(new ObjectMapper().readTree(it.next())); }
        assertEquals(3, values.size());
        var first = values.stream().filter(v -> v.get("intersection_id").asText().equals("i") && v.get("window_start").asText().endsWith("10:00:00Z")).findFirst().orElseThrow();
        assertEquals(2, first.get("reading_count").intValue()); assertEquals(20, first.get("average_speed").intValue());
        assertEquals("high", first.get("congestion").asText());
    }
    @Test void actualFlinkLateDataAndConflictingId() throws Exception {
        var env = StreamExecutionEnvironment.getExecutionEnvironment(); env.setParallelism(1);
        var watermarks = org.apache.flink.api.common.eventtime.WatermarkStrategy.<Reading>forGenerator(c -> new ImmediateWatermarks())
            .withTimestampAssigner((r, old) -> r.timestamp);
        var source = env.fromData(
            reading("a", "i", "00:10", "\"average_speed\":50"),
            reading("a", "different", "00:20", "\"average_speed\":0"),
            reading("advance", "control", "01:12", "\"vehicle_count\":0"),
            reading("late", "i", "00:30", "\"average_speed\":0"));
        List<com.fasterxml.jackson.databind.JsonNode> results = new ArrayList<>();
        try (var it = TrafficPipeline.build(source, watermarks).executeAndCollect()) {
            while (it.hasNext()) results.add(new ObjectMapper().readTree(it.next()));
        }
        assertEquals(2, results.size());
        var actual = results.stream().filter(n -> n.get("intersection_id").asText().equals("i")).findFirst().orElseThrow();
        assertEquals(1, actual.get("reading_count").intValue()); assertEquals(50, actual.get("average_speed").intValue());
    }
}
