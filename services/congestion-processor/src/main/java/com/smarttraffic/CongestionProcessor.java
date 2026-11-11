package com.smarttraffic;

/** Dependency-free liveness entry point; the actual Flink runtime enters FlinkJob. */
public final class CongestionProcessor {
    public static void main(String[] args) {
        if (args.length != 1 || !"--smoke".equals(args[0])) {
            try {
                Class.forName("com.smarttraffic.FlinkJob").getMethod("main", String[].class).invoke(null, (Object) args);
            } catch (ReflectiveOperationException e) {
                throw new IllegalStateException("Run the packaged job using a Flink runtime", e);
            }
            return;
        }
        System.out.println("{\"service\":\"congestion-processor\",\"status\":\"ok\",\"scope\":\"scaffold\"}");
    }
}
