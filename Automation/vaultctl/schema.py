from __future__ import annotations

import sqlite3


def ensure_schema_migrations(connection: sqlite3.Connection, schema_name: str, version: int) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            schema_name TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        INSERT INTO schema_migrations(schema_name, version)
        VALUES(?, ?)
        ON CONFLICT(schema_name) DO UPDATE SET
            version = excluded.version,
            applied_at = CURRENT_TIMESTAMP
        """,
        (schema_name, version),
    )
    connection.execute(f"PRAGMA user_version = {int(version)}")
