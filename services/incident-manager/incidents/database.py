"""Incident-only engine. No access to Registry tables or its SQLite file."""
import os
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base


class Database:
    def __init__(self, url=None):
        default = Path(__file__).resolve().parents[3] / ".data" / "incidents.db"
        url = url or os.environ.get("INCIDENT_MANAGER_DATABASE_URL", f"sqlite:///{default.as_posix()}")
        parsed = make_url(url)
        self.local = parsed.get_backend_name() == "sqlite"
        options = {"pool_pre_ping": True}
        if self.local:
            if parsed.database and parsed.database != ":memory:":
                Path(parsed.database).resolve().parent.mkdir(parents=True, exist_ok=True)
            options.update(connect_args={"check_same_thread": False, "timeout": 2},
                           execution_options={"schema_translate_map": {"incident_manager": None}})
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

    def initialize(self, create_tables=False):
        if self.local or create_tables:
            Base.metadata.create_all(self.engine)
        else:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
