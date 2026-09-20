"""SQLite persistence layer. All SQL in the project lives here.

Every query is parameterized (``?`` placeholders) to prevent SQL injection.
Each function accepts an optional ``db_path`` so tests can use a separate
database; by default the path is read from ``app.config`` at call time.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from app import config

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    test_type TEXT NOT NULL,
    voltage REAL NOT NULL,
    current REAL NOT NULL,
    temperature REAL NOT NULL,
    duration REAL NOT NULL,
    result TEXT NOT NULL,
    failure_reason TEXT,
    timestamp TEXT NOT NULL
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_test_results_device_id
ON test_results (device_id);
"""

INSERT_SQL = """
INSERT INTO test_results (
    device_id, test_type, voltage, current, temperature,
    duration, result, failure_reason, timestamp
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

STATISTICS_SELECT = """
SELECT
    COUNT(*) AS total_tests,
    COALESCE(SUM(CASE WHEN result = 'PASS' THEN 1 ELSE 0 END), 0) AS passed_tests,
    COALESCE(SUM(CASE WHEN result = 'FAIL' THEN 1 ELSE 0 END), 0) AS failed_tests,
    AVG(voltage) AS average_voltage,
    AVG(current) AS average_current,
    AVG(temperature) AS average_temperature
FROM test_results
"""


def current_timestamp() -> str:
    """UTC time as an ISO 8601 string without sub-seconds or offset."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


@contextmanager
def get_connection(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    """Open a connection that commits on success, rolls back on error, and closes."""
    connection = sqlite3.connect(db_path or config.DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:  # commit / rollback
            yield connection
    finally:
        connection.close()


def init_db(db_path: str | None = None) -> None:
    """Create the table and index if they do not exist yet."""
    with get_connection(db_path) as connection:
        connection.execute(CREATE_TABLE_SQL)
        connection.execute(CREATE_INDEX_SQL)


def insert_test(
    *,
    device_id: str,
    test_type: str,
    voltage: float,
    current: float,
    temperature: float,
    duration: float,
    result: str,
    failure_reason: str | None,
    timestamp: str | None = None,
    db_path: str | None = None,
) -> dict:
    """Insert a test result and return the stored record.

    ``timestamp`` defaults to the current UTC time; the data generator
    supplies its own so simulated tests are spread over several days.
    """
    timestamp = timestamp or current_timestamp()
    with get_connection(db_path) as connection:
        cursor = connection.execute(
            INSERT_SQL,
            (
                device_id,
                test_type,
                voltage,
                current,
                temperature,
                duration,
                result,
                failure_reason,
                timestamp,
            ),
        )
        row = connection.execute(
            "SELECT * FROM test_results WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return dict(row)


def get_test(test_id: int, db_path: str | None = None) -> dict | None:
    with get_connection(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM test_results WHERE id = ?", (test_id,)
        ).fetchone()
    return dict(row) if row else None


def get_all_tests(db_path: str | None = None) -> list[dict]:
    with get_connection(db_path) as connection:
        rows = connection.execute("SELECT * FROM test_results ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def get_device_tests(device_id: str, db_path: str | None = None) -> list[dict]:
    with get_connection(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM test_results WHERE device_id = ? ORDER BY id",
            (device_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_failed_tests(db_path: str | None = None) -> list[dict]:
    with get_connection(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM test_results WHERE result = ? ORDER BY id", ("FAIL",)
        ).fetchall()
    return [dict(row) for row in rows]


def delete_test(test_id: int, db_path: str | None = None) -> bool:
    """Delete a test. Returns True if a row was removed, False if it did not exist."""
    with get_connection(db_path) as connection:
        cursor = connection.execute("DELETE FROM test_results WHERE id = ?", (test_id,))
    return cursor.rowcount > 0


def get_statistics(db_path: str | None = None) -> dict:
    """Aggregate counts and averages across every stored test."""
    with get_connection(db_path) as connection:
        row = connection.execute(STATISTICS_SELECT).fetchone()
    return dict(row)


def get_device_statistics(device_id: str, db_path: str | None = None) -> dict:
    """Aggregate counts and averages for one device (total_tests is 0 if unknown)."""
    with get_connection(db_path) as connection:
        row = connection.execute(
            STATISTICS_SELECT + " WHERE device_id = ?", (device_id,)
        ).fetchone()
    return dict(row)
