# Phase 5 Step 8 managed DynamoDB evidence — 2026-11-11

The final temporary run, `stp5-20261111131637`, applied exactly five reviewed resources in
`ap-south-1`: two DynamoDB PAY_PER_REQUEST tables, two unattached owner policies, and the
Terraform guard. No EMR, MSK, EKS, network, Lambda, alert, or recovery-event resource was
created. The opt-in managed test passed in 58.535 seconds. It used the existing recommendation
rule and both service repositories to write known high-congestion windows, read them strongly,
query them by intersection/time, treat identical replays as unchanged, and reject changed-content
replays. It then started both existing FastAPI services with consumers disabled and queried the
actual AWS-backed REST APIs for detail, scoped pagination, cursor continuation and
cross-intersection isolation.

Terraform destroyed the same five state-owned resources. The runner recorded an empty Terraform
state and absence of both exact table names and policy ARNs. An independent AWS CLI audit after
the runner returned found no DynamoDB tables and no policies with the final run prefix.

Two earlier attempts are recorded honestly. Run `stp5-20261111125252` reached the test but
failed while Windows attempted to delete an open temporary log; its automatic cleanup passed.
Run `stp5-20261111125613` was interrupted after an unexpected delay; the recovery-only cleanup
destroyed its state-owned resources and a separate AWS check found no leftovers. The test now
uses Windows-tolerant temporary cleanup, and the final run passed.

The Kafka consumer/replay evidence remains a separate local Kafka-to-DynamoDB Local test from
Phase 5 Step 4. This managed run used AWS DynamoDB with local service processes and did not
provision or use MSK, EMR, or an AWS Kafka path. The separately documented Step 6 end-to-end
local demo subsequently passed against the existing local Kafka and DynamoDB Local setup; it is
not being conflated with this managed evidence.
