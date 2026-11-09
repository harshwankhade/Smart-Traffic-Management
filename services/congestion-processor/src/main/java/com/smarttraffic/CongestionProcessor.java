package com.smarttraffic;

/** Phase 1 entry-point check only. No Flink job or stream processing. */
public final class CongestionProcessor {
    public static void main(String[] args) {
        if (args.length != 1 || !"--smoke".equals(args[0])) {
            System.err.println("Phase 1 supports only --smoke; no Flink job is implemented.");
            System.exit(2);
        }
        System.out.println("{\"service\":\"congestion-processor\",\"status\":\"ok\",\"scope\":\"scaffold\"}");
    }
}
