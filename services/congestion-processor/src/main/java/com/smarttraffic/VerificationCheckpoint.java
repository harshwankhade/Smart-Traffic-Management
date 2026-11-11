package com.smarttraffic;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.flink.api.common.functions.RichMapFunction;
import org.apache.flink.api.common.state.CheckpointListener;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/** Reports a completed checkpoint only after both pending verification readings passed this operator. */
public final class VerificationCheckpoint extends RichMapFunction<String, String> implements CheckpointListener {
    private final String run;
    private final String bucket;
    private boolean firstPending;
    private boolean secondPending;

    public VerificationCheckpoint(String run, String bucket) {
        this.run = run;
        this.bucket = bucket;
    }

    @Override public String map(String raw) throws Exception {
        String eventId = new ObjectMapper().readTree(raw).path("event_id").asText();
        if (eventId.equals(run + "-pending")) firstPending = true;
        if (eventId.equals(run + "-pending2")) secondPending = true;
        return raw;
    }

    boolean ready() { return firstPending && secondPending; }

    @Override public void notifyCheckpointComplete(long checkpointId) throws Exception {
        if (!ready() || bucket.isBlank()) return;
        String key = "verification/" + run + "/checkpoint-ready.json";
        byte[] body = new ObjectMapper().writeValueAsBytes(Map.of("run", run, "checkpoint_id", checkpointId));
        try (S3Client s3 = S3Client.create()) {
            s3.putObject(PutObjectRequest.builder().bucket(bucket).key(key)
                .contentType("application/json").serverSideEncryption("AES256").build(),
                RequestBody.fromBytes(body));
        }
    }
}
