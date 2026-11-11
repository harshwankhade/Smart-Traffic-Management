# Congestion Processor - Phase 4

Java 17 Apache Flink 2.2.0 DataStream job; Kafka connector 4.0.0-2.0.
The dependency-free `--smoke` entry point remains liveness only.
Build with Maven 3.9.11: `mvn -f services/congestion-processor/pom.xml package`.
The shaded JAR uses runtime-provided Flink libraries; submit class `com.smarttraffic.FlinkJob`.

See [processing contract and local commands](../../docs/phase-4-processing.md),
[decisions](../../docs/decisions/phase-4.md), and [progress](../../docs/progress/phase-4.md).
Local integration is verified separately from the unexecuted AWS managed deployment.

# EMR on EC2 compatibility build

The approved cloud platform is Amazon EMR on EC2. AWS currently lists Flink 1.20 in EMR 7.14;
the default local build remains Flink 2.2. Build an EMR-targeted JAR with
`mvn -P emr -f services/congestion-processor/pom.xml package` and use the resulting
`target-emr/congestion-processor-1.0.0.jar` only after its tests pass. The separate target
directory preserves the local Flink 2.2 artifact. EMR execution, YARN
submission, MSK IAM and S3 checkpoint recovery are still unverified. EMR 7.14 is listed in Mumbai.
The temporary verification path also emits a receipt for a completed checkpoint after both
pending readings pass the source path; the cloud runner matches its checkpoint ID in S3 before
requesting stage-two restore.
