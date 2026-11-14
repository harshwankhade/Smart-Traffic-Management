"""Registry owns this engine and schema; no incident-table access."""
import os
import json
from pathlib import Path
from urllib.parse import quote_plus

import boto3

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base


class Database:
    def __init__(self, url=None):
        default = Path(__file__).resolve().parents[3] / ".data" / "registry.db"
        url = url or os.environ.get("SENSOR_REGISTRY_DATABASE_URL") or self._rds_url()
        url = url or f"sqlite:///{default.as_posix()}"
        parsed = make_url(url)
        self.local = parsed.get_backend_name() == "sqlite"
        options = {"pool_pre_ping": True}
        if self.local:
            if parsed.database and parsed.database != ":memory:":
                Path(parsed.database).resolve().parent.mkdir(parents=True, exist_ok=True)
            options.update(connect_args={"check_same_thread": False, "timeout": 2},
                           execution_options={"schema_translate_map": {"sensor_registry": None}})
            if parsed.database in (None, "", ":memory:"):
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        if self.local:
            @event.listens_for(self.engine, "connect")
            def enable_foreign_keys(connection, _):
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @staticmethod
    def _rds_url():
        """Use Pod Identity to read the RDS-managed credential only in AWS mode."""
        arn = os.environ.get("SENSOR_REGISTRY_DATABASE_SECRET_ARN")
        if not arn:
            return None
        value = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION")).get_secret_value(
            SecretId=arn)["SecretString"]
        credential = json.loads(value)
        return (f"postgresql+psycopg://{quote_plus(credential['username'])}:"
                f"{quote_plus(credential['password'])}@{credential['host']}:"
                f"{credential.get('port', 5432)}/smarttraffic")

    def initialize(self, create_tables=False):
        if self.local or create_tables:
            if create_tables and not self.local:
                with self.engine.begin() as connection:
                    connection.execute(text("CREATE SCHEMA IF NOT EXISTS sensor_registry"))
            Base.metadata.create_all(self.engine)
        else:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
