# event-publisher

Implemented Phase 3 service. See [API/delivery contract](../../docs/phase-3-api.md), [decisions](../../docs/decisions/phase-3.md), and [root setup](../../README.md).

Run from root using `.venv\Scripts\python scripts\run_service.py event-publisher --phase3-local` after configuring/starting/bootstrap of local infrastructure. Publisher runs one process with HTTP health plus actual gRPC. Ingestion validates Registry references before calling gRPC.

Use `scripts/demo_phase3.py --failure-tests` to verify actual local Kafka records and archive objects.

## Phase 7 Step 1 local election

ZooKeeper coordination is opt-in. Start the existing Phase 3 Kafka/archive dependencies, then start the local ZooKeeper container:

```powershell
docker compose -f infrastructure/local/phase7/compose.yaml up -d
```

Launch two publisher replicas with distinct HTTP and gRPC ports. The elected replica returns 200 from `/readyz`; the follower returns 503. `/coordination` identifies the local participant and leader state.

```powershell
$env:PUBLISHER_ZOOKEEPER_ENABLED='1'; $env:PUBLISHER_ZOOKEEPER_HOSTS='127.0.0.1:2181'
$env:PUBLISHER_INSTANCE_ID='publisher-a'; $env:PUBLISHER_GRPC_BIND='127.0.0.1:50051'; $env:PUBLISHER_ADVERTISED_GRPC_TARGET='127.0.0.1:50051'; $env:PUBLISHER_ADVERTISED_HTTP_URL='http://127.0.0.1:8003'
.venv\Scripts\python scripts\run_service.py event-publisher --phase3-local --port 8003
# In a second PowerShell window, retain the first two environment variables:
$env:PUBLISHER_INSTANCE_ID='publisher-b'; $env:PUBLISHER_GRPC_BIND='127.0.0.1:50052'; $env:PUBLISHER_ADVERTISED_GRPC_TARGET='127.0.0.1:50052'; $env:PUBLISHER_ADVERTISED_HTTP_URL='http://127.0.0.1:8004'
.venv\Scripts\python scripts\run_service.py event-publisher --phase3-local --port 8004
```

Stopping the leader removes its ephemeral node and promotes the follower. A suspended or lost ZooKeeper session rejects new publication immediately. On session expiry the process opens a fresh session and rejoins the election. This is bounded crash recovery only: it does not fence delayed in-flight Kafka writes or guarantee exactly-once delivery.

Traffic Ingestion can discover the elected publisher by starting it with `PUBLISHER_ZOOKEEPER_ENABLED=1`, `PUBLISHER_ZOOKEEPER_HOSTS=127.0.0.1:2181`, and optional bounded retry settings `PUBLISHER_FAILOVER_RETRY_ATTEMPTS=3` and `PUBLISHER_FAILOVER_RETRY_DELAY_SECONDS=0.15`. It resolves the current election node for every attempt and retains the original event ID. It retries only temporary discovery/publisher failures; a caller may still need to retry the same ID after the bounded attempts end.
