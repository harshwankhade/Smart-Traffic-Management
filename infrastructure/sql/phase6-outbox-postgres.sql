-- Upgrade an existing Phase 2 incident_manager schema before enabling Phase 6 delivery.
-- Apply with the incident_manager_owner role after reviewing the current schema.
BEGIN;
SET LOCAL ROLE incident_manager_owner;
CREATE TABLE IF NOT EXISTS incident_manager.alert_outbox (
    alert_id VARCHAR(256) PRIMARY KEY,
    incident_id VARCHAR(128) NOT NULL REFERENCES incident_manager.incidents (incident_id),
    request_json TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    sent_at TIMESTAMP WITH TIME ZONE,
    lease_token VARCHAR(128),
    lease_until TIMESTAMP WITH TIME ZONE,
    attempt_count INTEGER NOT NULL,
    last_error VARCHAR(128)
);
RESET ROLE;
COMMIT;
