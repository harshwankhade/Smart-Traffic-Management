package com.smarttraffic;

import com.amazonaws.services.kinesisanalytics.runtime.KinesisAnalyticsRuntime;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.flink.api.common.serialization.SimpleStringSchema;
import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.connector.kafka.source.KafkaSource;
import org.apache.flink.connector.kafka.source.enumerator.initializer.OffsetsInitializer;
import org.apache.flink.connector.kafka.sink.KafkaSink;
import org.apache.flink.connector.kafka.sink.KafkaRecordSerializationSchema;
import org.apache.flink.connector.base.DeliveryGuarantee;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.streaming.api.CheckpointingMode;
import org.apache.flink.configuration.Configuration;
import org.apache.flink.configuration.CheckpointingOptions;
import org.apache.flink.configuration.ExternalizedCheckpointRetention;
import org.apache.kafka.clients.producer.ProducerRecord;
import java.nio.charset.StandardCharsets;
import java.io.FileNotFoundException;
import java.util.Properties;

public final class FlinkJob {
    static Properties applicationSettings(String... args) throws Exception {
        Properties p = new Properties();
        p.putAll(System.getenv());
        try {
            var managed = KinesisAnalyticsRuntime.getApplicationProperties();
            if (managed.containsKey("Traffic")) p.putAll(managed.get("Traffic"));
        } catch (FileNotFoundException ignored) {
            // EMR and the local cluster do not supply a Managed Service properties file.
        }
        if (args.length % 2 != 0) throw new IllegalArgumentException("Application arguments must be --NAME value pairs");
        for (int i = 0; i < args.length; i += 2) {
            if (!args[i].startsWith("--") || args[i].length() == 2) {
                throw new IllegalArgumentException("Application argument names must start with --");
            }
            p.setProperty(args[i].substring(2), args[i + 1]);
        }
        return p;
    }
    public static void main(String[] args) throws Exception {
        Properties p = applicationSettings(args);
        String brokers = p.getProperty("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092");
        Properties kafka = new Properties();
        if (p.getProperty("KAFKA_AUTH_MODE", "local").equals("iam")) {
            kafka.setProperty("security.protocol", "SASL_SSL"); kafka.setProperty("sasl.mechanism", "AWS_MSK_IAM");
            kafka.setProperty("sasl.jaas.config", "software.amazon.msk.auth.iam.IAMLoginModule required;");
            kafka.setProperty("sasl.client.callback.handler.class", "software.amazon.msk.auth.iam.IAMClientCallbackHandler");
        }
        kafka.setProperty("allow.auto.create.topics", "false");
        kafka.setProperty("isolation.level", "read_committed");
        var env = StreamExecutionEnvironment.getExecutionEnvironment();
        env.setParallelism(1);
        env.enableCheckpointing(10000, CheckpointingMode.EXACTLY_ONCE);
        env.getCheckpointConfig().setCheckpointTimeout(60000);
        env.getCheckpointConfig().setMinPauseBetweenCheckpoints(5000);
        Configuration configuration = new Configuration();
        configuration.setString("restart-strategy.type", "fixed-delay");
        configuration.setString("restart-strategy.fixed-delay.attempts", "3");
        configuration.setString("restart-strategy.fixed-delay.delay", "2 s");
        configuration.set(CheckpointingOptions.EXTERNALIZED_CHECKPOINT_RETENTION, ExternalizedCheckpointRetention.RETAIN_ON_CANCELLATION);
        if (p.containsKey("CHECKPOINT_URI")) configuration.set(CheckpointingOptions.CHECKPOINTS_DIRECTORY, p.getProperty("CHECKPOINT_URI"));
        env.configure(configuration);
        var source = KafkaSource.<String>builder().setBootstrapServers(brokers).setProperties(kafka)
            .setTopics(p.getProperty("KAFKA_RAW_TOPIC", "traffic.raw"))
            .setGroupId(p.getProperty("KAFKA_GROUP_ID", "congestion-v1"))
            .setStartingOffsets(OffsetsInitializer.earliest()).setValueOnlyDeserializer(new SimpleStringSchema()).build();
        int verificationStage = Integer.parseInt(p.getProperty("VERIFICATION_STAGE", "0"));
        var readings = env.fromSource(source, WatermarkStrategy.noWatermarks(), "traffic.raw").uid("kafka-source-v1");
        if (verificationStage == 1) {
            readings = readings.map(new VerificationCheckpoint(p.getProperty("VERIFICATION_RUN_ID", ""),
                p.getProperty("VERIFICATION_BUCKET", ""))).name("verification-checkpoint").uid("verification-checkpoint-v1");
        }
        Properties producer = new Properties(); producer.putAll(kafka);
        producer.remove("isolation.level"); producer.remove("allow.auto.create.topics");
        producer.setProperty("enable.idempotence", "true"); producer.setProperty("acks", "all");
        producer.setProperty("delivery.timeout.ms", "10000"); producer.setProperty("request.timeout.ms", "3000");
        String topic = p.getProperty("KAFKA_RESULTS_TOPIC", "traffic.results");
        var sink = KafkaSink.<String>builder().setBootstrapServers(brokers).setKafkaProducerConfig(producer)
            .setDeliveryGuarantee(DeliveryGuarantee.AT_LEAST_ONCE)
            .setRecordSerializer(new KafkaRecordSerializationSchema<String>() {
                public ProducerRecord<byte[], byte[]> serialize(String value, KafkaSinkContext c, Long timestamp) {
                    try {
                        String key = new ObjectMapper().readTree(value).get("window_id").asText();
                        return new ProducerRecord<>(topic, key.getBytes(StandardCharsets.UTF_8), value.getBytes(StandardCharsets.UTF_8));
                    } catch (Exception e) { throw new IllegalArgumentException(e); }
                }
            }).build();
        TrafficPipeline.build(readings)
            .sinkTo(sink).name("traffic.results").uid("kafka-results-v1");
        if (verificationStage > 0) VerificationProbe.attach(env, brokers,
            p.getProperty("VERIFICATION_RUN_ID", "cloud-phase4"), kafka, verificationStage,
            p.getProperty("VERIFICATION_BUCKET", ""));
        env.execute("Smart Traffic Congestion v1");
    }
}
