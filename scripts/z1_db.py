"""Database configuration without printing secrets; no Docker dependency at runtime."""
from __future__ import annotations
import os
from pathlib import Path
import psycopg


def connect():
    env = {}
    path = Path(__file__).resolve().parents[1] / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key.startswith("POSTGRES_"):
                    env[key] = value.strip().strip("\"'")
    def setting(key, default=None):
        return os.environ.get(key, env.get(key, default))
    connection = psycopg.connect(host=setting("POSTGRES_HOST", "localhost"),
        port=setting("POSTGRES_PORT", "5432"), dbname=setting("POSTGRES_DB", "dbs2"),
        user=setting("POSTGRES_USER", "postgres"), password=setting("POSTGRES_PASSWORD"),
        autocommit=True, application_name="z1-etl")
    connection.execute("SET TimeZone='UTC'")
    return connection
