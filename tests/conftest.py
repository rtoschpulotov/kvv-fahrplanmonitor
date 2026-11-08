"""
Gemeinsame Fixture für alle Tests, die eine PostgreSQL-Datenbank brauchen.
Autor: Rustam T.

Die Verbindung kommt aus .env (der Docker-Container). Läuft keine
Datenbank, werden diese Tests übersprungen und nicht als Fehler gezählt.
Dann vorher `docker compose up -d`.

Jeder Test bekommt ein eigenes, leeres Schema, spielt sql/ dort ein und
löscht es danach wieder. Die echten Tabellen im Schema public bleiben
unberührt.
"""

import os
import uuid
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")


def _verbindung():
    return psycopg.connect(
        autocommit=True,
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=os.environ.get("POSTGRES_PORT", "5433"),
        user=os.environ.get("POSTGRES_USER", "kvv"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        dbname=os.environ.get("POSTGRES_DB", "kvv_fahrplan"),
        connect_timeout=3,
    )


@pytest.fixture
def db():
    try:
        conn = _verbindung()
    except psycopg.OperationalError as fehler:
        pytest.skip(f"keine PostgreSQL-Verbindung ({fehler}). Erst `docker compose up -d`.")
    schema = "test_" + uuid.uuid4().hex[:8]
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    for datei in sorted((REPO / "sql").glob("[0-9][0-9]_*.sql")):
        conn.execute(datei.read_text(encoding="utf-8"))
    yield conn
    conn.execute(f"DROP SCHEMA {schema} CASCADE")
    conn.close()
