package com.smarttraffic;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.flink.api.common.functions.OpenContext;
import org.apache.flink.api.common.functions.RichFlatMapFunction;
import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.api.common.serialization.SimpleStringSchema;
import org.apache.flink.connector.kafka.source.KafkaSource;
import org.apache.flink.connector.kafka.source.enumerator.initializer.OffsetsInitializer;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.util.Collector;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.slf4j.LoggerFactory;
import java.nio.charset.StandardCharsets;
import java.util.Properties;
import java.util.concurrent.TimeUnit;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;

/** Opt-in temporary verification tool in the same managed application, disabled by default. */
public class VerificationProbe extends RichFlatMapFunction<String, String> {
    private final String brokers, run;
    private final Properties authentication;
    private final String evidenceBucket;
    private final int stage;
    public VerificationProbe(String brokers, String run, Properties authentication, int stage) {
        this(brokers, run, authentication, stage, "");
    }
    public VerificationProbe(String brokers, String run, Properties authentication, int stage, String evidenceBucket) {
        this.brokers = brokers; this.run = run; this.authentication = authentication; this.stage = stage;
        this.evidenceBucket = evidenceBucket;
    }
    public static void attach(StreamExecutionEnvironment env, String brokers, String run, Properties auth, int stage, String evidenceBucket) {
        var source = KafkaSource.<String>builder().setBootstrapServers(brokers).setProperties(auth)
            .setTopics("traffic.results").setGroupId("congestion-verification-v1")
            .setStartingOffsets(OffsetsInitializer.earliest()).setValueOnlyDeserializer(new SimpleStringSchema()).build();
        env.fromSource(source, WatermarkStrategy.noWatermarks(), "verification-results").uid("verification-source-v1")
            .flatMap(new VerificationProbe(brokers, run, auth, stage, evidenceBucket)).name("verification-probe").uid("verification-probe-v1")
            .print("phase4-verification").uid("verification-log-v1");
    }
    public String sample(String id, String intersection, String clock, String measurements) {
        return "{\"schema_version\":\"1.0\",\"event_id\":\"" + run + "-" + id + "\",\"sensor_id\":\"cloud-verification\",\"intersection_id\":\"" + run + "-" + intersection
            + "\",\"observed_at\":\"2026-11-10T10:" + clock + "Z\"," + measurements + "}";
    }
    public void open(OpenContext context) throws Exception {
        Properties p = new Properties(); p.putAll(authentication);
        p.remove("isolation.level"); p.remove("allow.auto.create.topics");
        p.setProperty("bootstrap.servers", brokers);
        p.setProperty("key.serializer", "org.apache.kafka.common.serialization.StringSerializer");
        p.setProperty("value.serializer", "org.apache.kafka.common.serialization.StringSerializer");
        p.setProperty("acks", "all"); p.setProperty("enable.idempotence", "true");
        p.setProperty("delivery.timeout.ms", "60000");
        p.setProperty("reconnect.backoff.ms", "1000");
        try (KafkaProducer<String, String> producer = new KafkaProducer<>(p)) {
            String a = sample("a", "main", "00:00", "\"vehicle_count\":2,\"average_speed\":10,\"occupancy\":0.4");
            String pending = sample("pending", "main", "01:00", "\"average_speed\":45");
            if (stage == 1) {
                send(producer, a); send(producer, a);
                send(producer, sample("b", "main", "00:59.999999999", "\"vehicle_count\":3,\"average_speed\":30,\"occupancy\":0.8"));
                send(producer, sample("other", "other", "00:30", "\"vehicle_count\":7"));
                send(producer, pending);
                send(producer, sample("pending2", "main", "01:05", "\"average_speed\":25"));
                send(producer, sample("advance1", "watermark", "01:12", "\"vehicle_count\":0"));
            } else {
                send(producer, a); send(producer, pending);
                send(producer, sample("new", "main", "01:15", "\"average_speed\":50"));
                send(producer, sample("advance2", "watermark", "02:12", "\"vehicle_count\":0"));
            }
        }
        LoggerFactory.getLogger(VerificationProbe.class).info("PHASE4_INPUTS_ACKNOWLEDGED stage={} run={}", stage, run);
    }
    private void send(KafkaProducer<String, String> p, String json) throws Exception {
        String key = new ObjectMapper().readTree(json).get("intersection_id").asText();
        p.send(new ProducerRecord<>("traffic.raw", key, json)).get(65, TimeUnit.SECONDS);
    }
    public void flatMap(String raw, Collector<String> out) throws Exception {
        JsonNode result = new ObjectMapper().readTree(raw);
        if (!result.path("intersection_id").asText().equals(run + "-main")) return;
        boolean first = result.path("window_start").asText().equals("2026-11-10T10:00:00Z");
        boolean second = result.path("window_start").asText().equals("2026-11-10T10:01:00Z");
        if ((stage == 1 && !first) || (stage == 2 && !second)) return;
        boolean good;
        if (stage == 1) good = result.path("reading_count").asInt() == 2 && result.path("vehicle_count_sum").asInt() == 5
            && result.path("average_speed").asDouble() == 20 && result.path("average_occupancy").asDouble() == .6
            && result.path("congestion").asText().equals("medium");
        else good = result.path("reading_count").asInt() == 3 && result.path("vehicle_count_sum").isNull()
            && result.path("average_speed").asDouble() == 40 && result.path("average_occupancy").isNull()
            && result.path("congestion").asText().equals("low");
        if (!good) {
            LoggerFactory.getLogger(VerificationProbe.class).error("PHASE4_VERIFICATION_FAILED stage={} result={}", stage, raw);
            throw new IllegalStateException("Managed known-output mismatch");
        }
        if (!evidenceBucket.isBlank()) {
            String key = "verification/" + run + "/stage-" + stage + ".json";
            try (S3Client s3 = S3Client.create()) {
                s3.putObject(PutObjectRequest.builder().bucket(evidenceBucket).key(key)
                    .contentType("application/json").serverSideEncryption("AES256").build(),
                    RequestBody.fromString(raw, StandardCharsets.UTF_8));
            }
        }
        LoggerFactory.getLogger(VerificationProbe.class).info("PHASE4_VERIFIED_STAGE{} {}", stage, raw);
        out.collect(raw);
    }
}
