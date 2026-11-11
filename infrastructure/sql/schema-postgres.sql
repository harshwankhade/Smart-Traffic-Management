-- Initial PostgreSQL schema DDL compiled from the Phase 2 SQLAlchemy models.
-- Run bootstrap-postgres.sql first as the administrator. Not executed in Phase 2.
BEGIN;

SET LOCAL ROLE sensor_registry_owner;

CREATE TABLE IF NOT EXISTS sensor_registry.intersections (
	intersection_id VARCHAR(128) NOT NULL, 
	name TEXT NOT NULL, 
	location TEXT NOT NULL, 
	PRIMARY KEY (intersection_id)
);

CREATE TABLE IF NOT EXISTS sensor_registry.sensors (
	sensor_id VARCHAR(128) NOT NULL, 
	intersection_id VARCHAR(128) NOT NULL, 
	location TEXT NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	PRIMARY KEY (sensor_id), 
	CHECK (status IN ('active', 'inactive')), 
	FOREIGN KEY(intersection_id) REFERENCES sensor_registry.intersections (intersection_id)
);

RESET ROLE;

SET LOCAL ROLE incident_manager_owner;

CREATE TABLE IF NOT EXISTS incident_manager.incidents (
	incident_id VARCHAR(128) NOT NULL, 
	intersection_id VARCHAR(128) NOT NULL, 
	event_id VARCHAR(128) NOT NULL, 
	type VARCHAR(16) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	description TEXT NOT NULL, 
	reported_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	version INTEGER NOT NULL, 
	PRIMARY KEY (incident_id), 
	CHECK (status IN ('open', 'resolved')), 
	CHECK (type IN ('collision', 'closure', 'disruption')), 
	UNIQUE (event_id)
);

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
