"""Initialize the selected service's initial tables using its environment URL.

For PostgreSQL, run approved bootstrap SQL first and use an administrator/migration
identity. Runtime application roles have no schema creation privileges.
"""
import argparse
import importlib
import sys

from sqlalchemy import text

from smoke import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=("sensor-registry", "incident-manager"))
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "services" / args.service))
    package = "registry" if args.service == "sensor-registry" else "incidents"
    schema = "sensor_registry" if package == "registry" else "incident_manager"
    database = importlib.import_module(f"{package}.database").Database()
    models = importlib.import_module(f"{package}.models")
    try:
        if database.local:
            database.initialize()
        else:
            with database.engine.begin() as connection:
                connection.execute(text(f"SET LOCAL ROLE {schema}_owner"))
                models.Base.metadata.create_all(connection)
        print(f"Initialized {args.service} tables; no other service schema was changed")
    finally:
        database.engine.dispose()


if __name__ == "__main__":
    main()
