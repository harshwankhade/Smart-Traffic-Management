# PostgreSQL preparation - not executed

`bootstrap-postgres.sql` defines service-specific owner/application roles and isolated schemas inside the planned RDS `smarttraffic` database. No credentials are embedded. Runtime roles use RDS IAM database authentication; future IAM permissions and token delivery/renewal are not implemented in Phase 2. Never run application services with the master account.

`schema-postgres.sql` contains initial table definitions compiled from the SQLAlchemy models, with owner-role switching. These are initial schema definitions, not a migration history. They compile for PostgreSQL but have not been executed against a PostgreSQL server.

At a later authorized cloud step, use a private network connection and a verified RDS CA certificate to run bootstrap as the administrator, then run the initial schema file in the same database. The scripts are idempotent for initial creation; they do not upgrade existing tables or repair unrelated role memberships. Review existing schemas/roles before applying to a nonempty environment.

Alternatively, after bootstrap, `scripts/init_database.py sensor-registry` or `scripts/init_database.py incident-manager` creates only the selected service's initial tables using its environment database URL. On PostgreSQL it switches to that service's owner role. Runtime application roles cannot initialize schemas. Normal app startup auto-creates SQLite tables only; PostgreSQL startup verifies connectivity and does not create or migrate tables.

Configuration uses `SENSOR_REGISTRY_DATABASE_URL` and `INCIDENT_MANAGER_DATABASE_URL`. For PostgreSQL install `requirements-postgres.txt`; inject a service-specific URL using `postgresql+psycopg`, `sslmode=verify-full` and the RDS CA file path via `sslrootcert`. Do not place real URLs containing credentials/tokens in documentation, version control, command arguments or Terraform outputs. Protect and refresh runtime credentials outside these initial-schema tools.

Local SQLite uses separate files and service metadata maps each logical schema to its own file. PostgreSQL role isolation, SQL execution, TLS and token renewal remain unverified cloud integration tasks. SQLite tests are not proof of those behaviors.
