"""Oracle persistence layer, the second backend next to ``app.database``.

It exposes the same functions as the SQLite layer and returns records in the
same shape. Writes and statistics go through the PL/SQL package
``test_stats_pkg``; reads use the ``v_test_report`` and ``v_failed_tests``
views. Every value is passed as a bind variable, never built into the SQL.

The schema, views and package live in ``db/oracle`` as plain ``.sql`` files.
"""

import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

import oracledb

from app import config
from app.database import REPORT_COLUMNS, current_timestamp

SQL_DIR = Path(__file__).resolve().parent.parent / "db" / "oracle"
SCHEMA_FILES = ("schema.sql", "views.sql", "test_stats_pkg.sql")
DROP_FILE = "drop.sql"

TEST_SELECT = """
SELECT result_id, device_code, test_type, voltage_v, current_a,
       temperature_c, duration_s, result, failure_reason, tested_at
FROM {source}
"""

RECORD_TEST_SQL = """
BEGIN
    test_stats_pkg.record_test_result(
        p_device_code    => :device_code,
        p_test_type      => :test_type,
        p_voltage_v      => :voltage,
        p_current_a      => :current_a,
        p_temperature_c  => :temperature,
        p_duration_s     => :duration,
        p_result         => :result,
        p_failure_reason => :failure_reason,
        p_tested_at      => :tested_at,
        p_result_id      => :result_id
    );
END;
"""

STATISTICS_KEYS = (
    "total_tests",
    "passed_tests",
    "failed_tests",
    "average_voltage",
    "average_current",
    "average_temperature",
)

_pool: oracledb.ConnectionPool | None = None


def read_statements(path: Path) -> list[str]:
    """Split a ``.sql`` file into statements on lines that contain only ``/``."""
    statements = []
    for chunk in re.split(r"^/[ \t]*$", path.read_text(encoding="utf-8"), flags=re.MULTILINE):
        lines = chunk.strip().splitlines()
        while lines and (not lines[0].strip() or lines[0].lstrip().startswith("--")):
            lines.pop(0)
        if lines:
            statements.append("\n".join(lines))
    return statements


def get_pool() -> oracledb.ConnectionPool:
    """Create the connection pool on first use from the ORACLE_* settings."""
    global _pool
    if _pool is None:
        if not (config.ORACLE_USER and config.ORACLE_PASSWORD):
            raise RuntimeError(
                "The Oracle backend needs ORACLE_USER and ORACLE_PASSWORD "
                "(see .env.example)"
            )
        _pool = oracledb.create_pool(
            user=config.ORACLE_USER,
            password=config.ORACLE_PASSWORD,
            dsn=config.ORACLE_DSN,
            min=1,
            max=4,
            increment=1,
        )
    return _pool


def close_pool() -> None:
    """Close the pool so the next call reconnects with the current settings."""
    global _pool
    if _pool is not None:
        _pool.close(force=True)
        _pool = None


@contextmanager
def get_connection() -> Iterator[oracledb.Connection]:
    """Borrow a pooled connection; commit on success, roll back on error."""
    connection = get_pool().acquire()
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()  # hands the connection back to the pool


def _run_files(filenames: tuple[str, ...]) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for filename in filenames:
                for statement in read_statements(SQL_DIR / filename):
                    cursor.execute(statement)


def _check_package_compiled() -> None:
    """Oracle creates an invalid package without raising, so check for errors."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name, type, line, text FROM user_errors "
                "WHERE name = :name ORDER BY type, sequence",
                name="TEST_STATS_PKG",
            )
            errors = cursor.fetchall()
    if errors:
        details = "; ".join(f"{kind} line {line}: {text.strip()}" for _, kind, line, text in errors)
        raise RuntimeError(f"test_stats_pkg did not compile: {details}")


def init_db() -> None:
    """Create the tables, indexes, views and PL/SQL package if they are missing."""
    _run_files(SCHEMA_FILES)
    _check_package_compiled()


def reset_db() -> None:
    """Drop every project object and rebuild the schema, so ids start at 1 again."""
    _run_files((DROP_FILE,))
    init_db()


def _to_record(row: tuple) -> dict:
    """Shape a row of TEST_SELECT like a row from the SQLite backend."""
    return {
        "id": row[0],
        "device_id": row[1],
        "test_type": row[2],
        "voltage": row[3],
        "current": row[4],
        "temperature": row[5],
        "duration": row[6],
        "result": row[7],
        "failure_reason": row[8],
        "timestamp": row[9].isoformat(timespec="seconds"),
    }


def _select_tests(source: str, where: str = "", **binds) -> list[dict]:
    sql = TEST_SELECT.format(source=source) + where + " ORDER BY result_id"
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, binds)
            return [_to_record(row) for row in cursor.fetchall()]


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
) -> dict:
    """Store a test through ``test_stats_pkg.record_test_result`` and return it.

    Raises ``ValueError`` when the procedure rejects the values.
    """
    tested_at = datetime.fromisoformat(timestamp or current_timestamp())
    with get_connection() as connection:
        with connection.cursor() as cursor:
            result_id = cursor.var(oracledb.DB_TYPE_NUMBER)
            cursor.setinputsizes(
                voltage=oracledb.DB_TYPE_BINARY_DOUBLE,
                current_a=oracledb.DB_TYPE_BINARY_DOUBLE,
                temperature=oracledb.DB_TYPE_BINARY_DOUBLE,
                duration=oracledb.DB_TYPE_BINARY_DOUBLE,
                tested_at=oracledb.DB_TYPE_TIMESTAMP,
            )
            try:
                cursor.execute(
                    RECORD_TEST_SQL,
                    device_code=device_id,
                    test_type=test_type,
                    voltage=voltage,
                    current_a=current,
                    temperature=temperature,
                    duration=duration,
                    result=result,
                    failure_reason=failure_reason,
                    tested_at=tested_at,
                    result_id=result_id,
                )
            except oracledb.DatabaseError as exc:
                (error,) = exc.args
                if 20000 <= error.code <= 20999:  # raised by the package
                    raise ValueError(error.message.splitlines()[0]) from exc
                raise
            cursor.execute(
                TEST_SELECT.format(source="v_test_report") + " WHERE result_id = :result_id",
                result_id=result_id.getvalue(),
            )
            return _to_record(cursor.fetchone())


def get_test(test_id: int) -> dict | None:
    rows = _select_tests("v_test_report", " WHERE result_id = :result_id", result_id=test_id)
    return rows[0] if rows else None


def get_all_tests() -> list[dict]:
    return _select_tests("v_test_report")


def get_device_tests(device_id: str) -> list[dict]:
    return _select_tests(
        "v_test_report", " WHERE device_code = :device_code", device_code=device_id
    )


def get_failed_tests() -> list[dict]:
    return _select_tests("v_failed_tests")


def delete_test(test_id: int) -> bool:
    """Delete a test. Returns True if a row was removed, False if it did not exist."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM test_results WHERE result_id = :result_id", result_id=test_id
            )
            return cursor.rowcount > 0


def _fetch_dicts(ref_cursor: oracledb.Cursor) -> list[dict]:
    """Read every row of a ref cursor as a dict keyed by lower-case column name."""
    names = [column[0].lower() for column in ref_cursor.description]
    return [dict(zip(names, row)) for row in ref_cursor.fetchall()]


def _call_get_statistics() -> tuple[dict, list[dict]]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            overall = cursor.var(oracledb.DB_TYPE_CURSOR)
            per_device = cursor.var(oracledb.DB_TYPE_CURSOR)
            cursor.callproc("test_stats_pkg.get_statistics", [overall, per_device])
            return (
                _fetch_dicts(overall.getvalue())[0],
                _fetch_dicts(per_device.getvalue()),
            )


def get_statistics() -> dict:
    """Aggregate counts and averages across every stored test."""
    overall, _ = _call_get_statistics()
    return overall


def get_statistics_by_device() -> list[dict]:
    """The same aggregates for each device, plus the pass rate worked out in SQL."""
    _, per_device = _call_get_statistics()
    for row in per_device:
        row["pass_rate"] = float(row["pass_rate"])
    return per_device


def get_device_statistics(device_id: str) -> dict:
    """Aggregate counts and averages for one device (total_tests is 0 if unknown)."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            stats = cursor.var(oracledb.DB_TYPE_CURSOR)
            cursor.callproc("test_stats_pkg.get_device_statistics", [device_id, stats])
            return _fetch_dicts(stats.getvalue())[0]


def get_device_pass_rate(device_id: str) -> float | None:
    """Pass rate from ``test_stats_pkg.device_pass_rate``; None if the device has no tests."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            return cursor.callfunc(
                "test_stats_pkg.device_pass_rate", oracledb.DB_TYPE_BINARY_DOUBLE, [device_id]
            )


def get_report_rows() -> list[dict]:
    """Every test as a flat reporting row, read from the ``v_test_report`` view."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT result_id, device_code, test_type, result, passed, failed, "
                "voltage_v, current_a, temperature_c, duration_s, voltage_fault, "
                "current_fault, temperature_fault, duration_fault, failure_reason, "
                "tested_at, test_date FROM v_test_report ORDER BY result_id"
            )
            rows = []
            for row in cursor.fetchall():
                record = dict(zip(REPORT_COLUMNS, row))
                record["tested_at"] = record["tested_at"].isoformat(timespec="seconds")
                record["test_date"] = record["test_date"].date().isoformat()
                rows.append(record)
            return rows
