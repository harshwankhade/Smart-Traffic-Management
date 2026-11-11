package com.smarttraffic;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.api.common.functions.AggregateFunction;
import org.apache.flink.api.common.state.ValueState;
import org.apache.flink.api.common.state.ValueStateDescriptor;
import org.apache.flink.api.common.state.StateTtlConfig;
import org.apache.flink.api.common.functions.OpenContext;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.functions.KeyedProcessFunction;
import org.apache.flink.streaming.api.functions.windowing.ProcessWindowFunction;
import org.apache.flink.streaming.api.windowing.assigners.TumblingEventTimeWindows;
import org.apache.flink.streaming.api.windowing.windows.TimeWindow;
import org.apache.flink.util.Collector;
import org.apache.flink.util.OutputTag;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.math.MathContext;
import java.time.Duration;
import java.time.Instant;
import java.io.Serializable;
import java.util.LinkedHashMap;

public final class TrafficPipeline {
    public static final OutputTag<Reading> LATE = new OutputTag<Reading>("late-readings") {};
    public static DataStream<String> build(DataStream<String> source) {
        return build(source, WatermarkStrategy.<Reading>forBoundedOutOfOrderness(Duration.ofSeconds(10))
            .withTimestampAssigner((r, previous) -> r.timestamp).withIdleness(Duration.ofSeconds(30)));
    }
    static DataStream<String> build(DataStream<String> source, WatermarkStrategy<Reading> watermarks) {
        DataStream<Reading> parsed = source.flatMap(new org.apache.flink.api.common.functions.RichFlatMapFunction<String, Reading>() {
            private transient org.apache.flink.metrics.Counter invalid;
            public void open(OpenContext c) { invalid = getRuntimeContext().getMetricGroup().counter("invalid_readings"); }
            public void flatMap(String raw, Collector<Reading> out) {
                Reading reading;
                try { reading = Reading.parse(raw); }
                catch (Exception e) { invalid.inc(); System.err.println("invalid_reading: " + e.getClass().getSimpleName()); return; }
                out.collect(reading);
            }
        }).returns(Reading.class).name("validate-reading").uid("validate-v1")
            .assignTimestampsAndWatermarks(watermarks);
        DataStream<Reading> unique = parsed.keyBy(r -> r.eventId).process(new Deduplicate()).name("event-id-deduplication").uid("dedup-v1");
        var windows = unique.keyBy(r -> r.intersectionId)
            .window(TumblingEventTimeWindows.of(Duration.ofSeconds(60))).allowedLateness(Duration.ZERO)
            .sideOutputLateData(LATE).aggregate(new Aggregate(), new Finish()).name("intersection-minute-windows").uid("windows-v1");
        windows.getSideOutput(LATE).process(new org.apache.flink.streaming.api.functions.ProcessFunction<Reading, String>() {
            private transient org.apache.flink.metrics.Counter late;
            public void open(OpenContext c) { late = getRuntimeContext().getMetricGroup().counter("late_readings"); }
            public void processElement(Reading r, Context c, Collector<String> out) {
                late.inc(); System.err.println("late_reading excluded intersection=" + r.intersectionId + " timestamp=" + r.timestamp);
            }
        }).name("count-late-readings").uid("late-v1").print("late-audit");
        return windows;
    }
    public static class Deduplicate extends KeyedProcessFunction<String, Reading, Reading> {
        private transient ValueState<String> seen;
        private transient org.apache.flink.metrics.Counter duplicate, conflict, replay;
        public void open(OpenContext c) {
            ValueStateDescriptor<String> d = new ValueStateDescriptor<>("event-fingerprint-v1", String.class);
            d.enableTimeToLive(StateTtlConfig.newBuilder(Duration.ofHours(24))
                .setUpdateType(StateTtlConfig.UpdateType.OnCreateAndWrite)
                .setStateVisibility(StateTtlConfig.StateVisibility.NeverReturnExpired).build());
            seen = getRuntimeContext().getState(d);
            duplicate = getRuntimeContext().getMetricGroup().counter("duplicate_readings");
            conflict = getRuntimeContext().getMetricGroup().counter("conflicting_readings");
            replay = getRuntimeContext().getMetricGroup().counter("replay_horizon_rejections");
        }
        public void processElement(Reading r, Context ctx, Collector<Reading> out) throws Exception {
            // Very old replay is never newly aggregated, even after processing-time TTL expires.
            if (ctx.timerService().currentWatermark() != Long.MIN_VALUE &&
                r.timestamp < ctx.timerService().currentWatermark() - Duration.ofHours(24).toMillis()) {
                replay.inc(); System.err.println("replay_beyond_horizon excluded timestamp=" + r.timestamp); return;
            }
            String previous = seen.value();
            if (previous != null) { if (previous.equals(r.fingerprint)) duplicate.inc(); else conflict.inc(); return; }
            seen.update(r.fingerprint); out.collect(r);
        }
    }
    public static class Summary implements Serializable {
        public long readings, speedN, occupancyN, countN;
        public BigInteger count = BigInteger.ZERO;
        public BigDecimal speed = BigDecimal.ZERO, occupancy = BigDecimal.ZERO;
        public Summary() {}
    }
    public static class Aggregate implements AggregateFunction<Reading, Summary, Summary> {
        public Summary createAccumulator() { return new Summary(); }
        public Summary add(Reading r, Summary s) {
            s.readings++;
            if (r.count != null) { s.countN++; s.count = s.count.add(r.count); }
            if (r.speed != null) { s.speedN++; s.speed = s.speed.add(r.speed); }
            if (r.occupancy != null) { s.occupancyN++; s.occupancy = s.occupancy.add(r.occupancy); }
            return s;
        }
        public Summary getResult(Summary s) { return s; }
        public Summary merge(Summary a, Summary b) {
            a.readings += b.readings; a.speedN += b.speedN; a.occupancyN += b.occupancyN; a.countN += b.countN;
            a.count = a.count.add(b.count); a.speed = a.speed.add(b.speed); a.occupancy = a.occupancy.add(b.occupancy); return a;
        }
    }
    public static String result(String intersection, long start, long end, Summary s) throws Exception {
        BigDecimal speed = s.speedN == 0 ? null : s.speed.divide(BigDecimal.valueOf(s.speedN), MathContext.DECIMAL128);
        BigDecimal occupancy = s.occupancyN == 0 ? null : s.occupancy.divide(BigDecimal.valueOf(s.occupancyN), MathContext.DECIMAL128);
        String level = "unknown";
        if (speed != null || occupancy != null) {
            if ((speed != null && speed.compareTo(BigDecimal.valueOf(20)) < 0) || (occupancy != null && occupancy.compareTo(new BigDecimal("0.80")) >= 0)) level = "high";
            else if ((speed != null && speed.compareTo(BigDecimal.valueOf(40)) < 0) || (occupancy != null && occupancy.compareTo(new BigDecimal("0.50")) >= 0)) level = "medium";
            else level = "low";
        }
        var result = new LinkedHashMap<String, Object>();
        String first = Instant.ofEpochMilli(start).toString(), last = Instant.ofEpochMilli(end).toString();
        result.put("schema_version", "1.0"); result.put("window_id", intersection + "/" + first + "/" + last + "/v1");
        result.put("intersection_id", intersection); result.put("window_start", first); result.put("window_end", last);
        result.put("reading_count", s.readings); result.put("vehicle_count_sum", s.countN == 0 ? null : s.count);
        result.put("average_speed", speed); result.put("average_occupancy", occupancy); result.put("congestion", level);
        return new ObjectMapper().writeValueAsString(result);
    }
    public static class Finish extends ProcessWindowFunction<Summary, String, String, TimeWindow> {
        public void process(String key, Context c, Iterable<Summary> values, Collector<String> out) throws Exception {
            out.collect(result(key, c.window().getStart(), c.window().getEnd(), values.iterator().next()));
        }
    }
}
