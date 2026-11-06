"""SQLite connection helper for PayGate database modules."""

import sqlite3
from pathlib import Path


def get_connection(database_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with foreign-key enforcement enabled."""
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
