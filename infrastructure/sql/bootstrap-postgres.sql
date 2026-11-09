-- Planned bootstrap only; not run against PostgreSQL in Phase 2.
-- Run as RDS administrator in database smarttraffic with TLS. Never use the
-- administrator URL for application workloads. No passwords are embedded here.
BEGIN;
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sensor_registry_owner') THEN
    CREATE ROLE sensor_registry_owner NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'incident_manager_owner') THEN
    CREATE ROLE incident_manager_owner NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sensor_registry_app') THEN
    CREATE ROLE sensor_registry_app LOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'incident_manager_app') THEN
    CREATE ROLE incident_manager_app LOGIN;
  END IF;
  EXECUTE format('GRANT sensor_registry_owner, incident_manager_owner TO %I', current_user);
END $$;
GRANT rds_iam TO sensor_registry_app, incident_manager_app;
REVOKE ALL ON DATABASE smarttraffic FROM PUBLIC;
GRANT CONNECT ON DATABASE smarttraffic TO sensor_registry_app, incident_manager_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA IF NOT EXISTS sensor_registry AUTHORIZATION sensor_registry_owner;
CREATE SCHEMA IF NOT EXISTS incident_manager AUTHORIZATION incident_manager_owner;
REVOKE ALL ON SCHEMA sensor_registry, incident_manager FROM PUBLIC;
GRANT USAGE ON SCHEMA sensor_registry TO sensor_registry_app;
GRANT USAGE ON SCHEMA incident_manager TO incident_manager_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sensor_registry_owner IN SCHEMA sensor_registry
  GRANT SELECT, INSERT, UPDATE ON TABLES TO sensor_registry_app;
ALTER DEFAULT PRIVILEGES FOR ROLE incident_manager_owner IN SCHEMA incident_manager
  GRANT SELECT, INSERT, UPDATE ON TABLES TO incident_manager_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA sensor_registry TO sensor_registry_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA incident_manager TO incident_manager_app;
COMMIT;
