"""Small helpers to open the SQLite database and create the schema."""

import sqlite3
from pathlib import Path

from refund_agent import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open the database. Rows behave like dicts (row["name"]) thanks to sqlite3.Row."""
    conn = sqlite3.connect(db_path or config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables from schema.sql."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
