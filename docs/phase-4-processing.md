# Phase 4 processing contract

Status: real local Java 17 Flink/Kafka and a temporary EMR on EC2 execution verified; cloud stack removed.

## Inputs, state and outputs

Read normalized `contracts/v1/reading.schema.json` events from `traffic.raw`. The processor
validates structural/range constraints again; Registry identity validation remains Ingestion's
responsibility. Invalid Kafka input is counted and excluded. No Registry calls occur in Flink.
Optional zeros remain present, while missing values remain absent. Timestamp fractions beyond
milliseconds are floored only for window assignment, without changing the source event.

Partition keyed deduplication by globally stable `event_id`, followed by intersection-keyed
60-second tumbling event-time windows `[start,end)`. Ten-second bounded out-of-order watermarks
and 30-second idle detection apply. At millisecond resolution Flink fires a window when the
watermark reaches `end - 1 ms`. Later readings go to the counted/logged late side output;
there are no corrective updates. Idleness does not advance event time when every input is idle:
send later timestamped synthetic readings to finalize demo windows. Never substitute wall time.

Deduplication stores the first valid event's canonical field representation in Flink keyed state,
with a 24-hour processing-time TTL measured from first insertion, not extended by retries.
Identical retry is dropped; changed-content reuse is counted and dropped. Publisher already
prevents conflicting IDs on the normal ingestion path. Readings more than 24 hours behind the
current watermark are rejected and counted. Normal window lateness excludes older finalized
windows even inside that horizon. TTL expiration is configured, not claimed wall-clock soak-tested.

For each window, count distinct readings, sum present counts using arbitrary-precision integers,
and calculate arithmetic means for present speed and occupancy independently using DECIMAL128
division. Missing measurement summaries are JSON null; count-only congestion is `unknown`.
`high`: speed <20 or occupancy >=0.8; else `medium`: speed <40 or occupancy >=0.5;
else `low` if either signal exists. Empty windows produce no record.

Emit `contracts/v1/result.schema.json` on the distinct `traffic.results` topic.
Both Kafka key and `window_id` are `intersection_id/window_start/window_end/v1`.
The approved schema is unchanged. Decimal values are JSON numbers; windows use canonical UTC `Z`.

## Recovery and delivery

Checkpoint every ten seconds, timeout sixty seconds, minimum pause five seconds. Source offsets,
dedup state and pending aggregates participate in Flink's checkpoint. Stable operator UIDs must
be retained. Local checkpoints use a persistent Docker volume mounted at `/checkpoints` on both
managers. Three fixed-delay recovery attempts are configured. The EMR build uses a private
run-owned S3 checkpoint path, never the local file URI. The historical managed-service build
used service-owned snapshots; the approved EMR run restored an explicitly selected completed
S3 checkpoint.

The Kafka results sink is **at least once** with producer idempotence and `acks=all`.
Recovery can repeat results under stable window keys. Consumers must upsert by key; no
end-to-end exactly-once guarantee is made. Restoring a checkpoint is not equivalent to starting
without state. Earliest-offset startup without restoration is an explicit full state rebuild;
do not use it for ordinary recovery. Rebuilds may classify historical late data differently;
use an isolated output topic/namespace and reconcile intentionally before replacing live results.
The local demo uses unique synthetic intersection namespaces and retains historical test records.

## Reproducible local workflow (PowerShell, project root)

Requirements: Docker Desktop, Python environment from README, Maven 3.9.11 and Java.
Compilation/tests ran with JDK 21 targeting release 17; actual container integration uses Java 17.

```powershell
mvn -f services/congestion-processor/pom.xml package
.venv\Scripts\python scripts\phase3_local.py configure
.venv\Scripts\python scripts\phase4_local.py up
.venv\Scripts\python scripts\demo_phase4.py --report docs/evidence/phase-4-verification.json
.venv\Scripts\python scripts\inspect_phase4.py --seconds 10
.venv\Scripts\python scripts\phase4_local.py status
.venv\Scripts\python scripts\phase4_local.py down
```

`up` requires the built JAR, preserves Kafka/archive data and adds only the internal Docker
Kafka listener and one-partition results topic (RF1, minISR1, 24-hour deletion retention).
Flink uses `kafka:19092`; host services retain `127.0.0.1:9092`. Only loopback port 8081
is exposed for Flink REST. Named-volume permission handling uses root locally only.
After rebuilding the JAR, rerun `phase4_local.py up` to recreate the inactive Flink containers
and remount the new artifact; the command refuses to disrupt an active job.

The demo submits its own job, feeds actual Kafka with independent known-value expectations,
tests duplicates and a post-watermark late reading, waits for a checkpoint, cancels the job,
restarts the cluster, explicitly restores the checkpoint, retries old IDs and finishes the pending
window. It validates result schemas, keys, numeric summaries and checkpoint metadata. It cancels
its job in `finally`; containers and volumes remain for inspection. It rejects overlapping jobs.
Direct Kafka test input isolates processor verification; Phase 3's demo verifies the REST/gRPC path.

For a manually managed initial job use `phase4_local.py submit`; for recovery use
`phase4_local.py submit --restore file:/checkpoints/<job>/chk-<number>`. Cluster logs and the
REST UI at `http://127.0.0.1:8081` expose checkpoints and invalid/duplicate/conflict/late/replay counters.
The helper never deletes volumes or unrelated containers. Stop Phase 4 before stopping Phase 3.

## Cloud boundary

See [Terraform deployment preparation](../infrastructure/terraform/phase4/README.md).
The EMR 7.14 build uses Flink 1.20 and retained checkpoints in the existing private S3 bucket.
The temporary verification branch publishes fixed raw readings inside the dedicated EMR cluster,
checks actual Kafka results, and writes a stage result marker to S3. A checkpoint listener on the
raw path writes a separate marker only after both pending readings have passed the operator and
Flink has completed a checkpoint. The runner restores from the matching `chk-N` metadata path;
it does not pick an older or unrelated checkpoint by object modification time. Stage two checks
the restored pending window and repeated event IDs. Temporary run `stp4-91dd0a43a8` verified
private IAM/TLS MSK, EMR YARN submission and S3 checkpoint restoration. Both EMR steps completed;
actual Kafka-derived results matched the approved schema and expected fields. The stack was
destroyed and independently audited; see [managed evidence](evidence/phase-4-cloud.json) and
[cleanup audit](evidence/phase-4-cleanup.json). This does not prove exactly-once delivery or the
full cloud application's operation. No public broker, NAT gateway or ninth service was added.

# EMR on EC2 build status

The approved cloud target is now Amazon EMR on EC2. Use Maven profile `emr` to build against
Flink 1.20.0 and Kafka connector 3.4.0-1.20 into `services/congestion-processor/target-emr/`.
The normal Flink 2.2 build remains in `target/`. Seven Java tests passed per profile in the
local preflight; the separate temporary EMR run supplied the managed Kafka/checkpoint evidence.

