"""Proof that the SQLite and Oracle backends agree on the same seeded data.

Both databases are loaded once with the 500 simulated results (20 devices,
seed 42), then every read is compared. Skipped when Oracle is not running.
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import config, database, services
from app.main import app
from bi import export_results
from scripts.generate_test_data import generate_rows

DEVICES = [f"FPGA-{number:03d}" for number in range(1, 21)]


@pytest.fixture(scope="module")
def seeded(oracle_ready, tmp_path_factory):
    """(sqlite path, oracle module) holding identical rows."""
    rows = generate_rows(devices=20, tests_per_device=25, seed=42, now=datetime(2026, 10, 1))
    sqlite_path = str(tmp_path_factory.mktemp("parity") / "parity.db")
    database.init_db(sqlite_path)
    oracle_ready.reset_db()
    for row in rows:
        database.insert_test(**row, db_path=sqlite_path)
        oracle_ready.insert_test(**row)
    return sqlite_path, oracle_ready


def test_both_backends_hold_the_500_seeded_results(seeded):
    sqlite_path, oracle = seeded
    assert database.get_statistics(sqlite_path)["total_tests"] == 500
    assert oracle.get_statistics()["total_tests"] == 500


def test_every_stored_record_is_identical(seeded):
    sqlite_path, oracle = seeded
    assert oracle.get_all_tests() == database.get_all_tests(sqlite_path)


def test_failed_tests_are_identical(seeded):
    sqlite_path, oracle = seeded
    failures = oracle.get_failed_tests()
    assert failures == database.get_failed_tests(sqlite_path)
    assert len(failures) == 53


def test_overall_statistics_are_identical(seeded):
    sqlite_path, oracle = seeded
    from_sqlite = database.get_statistics(sqlite_path)
    from_oracle = oracle.get_statistics()
    assert set(from_oracle) == set(from_sqlite)
    for key in ("total_tests", "passed_tests", "failed_tests"):
        assert from_oracle[key] == from_sqlite[key]
    # Averages are sums of doubles added in a different order, so compare the
    # raw values to 12 significant figures and the reported values exactly.
    for key in ("average_voltage", "average_current", "average_temperature"):
        assert from_oracle[key] == pytest.approx(from_sqlite[key], rel=1e-12)
    assert services.build_statistics(from_oracle) == services.build_statistics(from_sqlite)


@pytest.mark.parametrize("device_id", [*DEVICES, "NOPE"])
def test_device_statistics_are_identical(seeded, device_id):
    sqlite_path, oracle = seeded
    from_sqlite = services.build_statistics(database.get_device_statistics(device_id, sqlite_path))
    from_oracle = services.build_statistics(oracle.get_device_statistics(device_id))
    assert from_oracle == from_sqlite


def test_device_test_lists_are_identical(seeded):
    sqlite_path, oracle = seeded
    for device_id in DEVICES:
        assert oracle.get_device_tests(device_id) == database.get_device_tests(device_id, sqlite_path)


def test_plsql_per_device_cursor_matches_sqlite(seeded):
    sqlite_path, oracle = seeded
    per_device = oracle.get_statistics_by_device()
    assert [row["device_id"] for row in per_device] == DEVICES
    for row in per_device:
        expected = services.build_statistics(
            database.get_device_statistics(row["device_id"], sqlite_path)
        )
        assert row["total_tests"] == expected["total_tests"]
        assert row["passed_tests"] == expected["passed_tests"]
        assert row["failed_tests"] == expected["failed_tests"]
        assert row["pass_rate"] == expected["pass_rate"]


def test_plsql_pass_rate_function_matches_python(seeded):
    sqlite_path, oracle = seeded
    for device_id in DEVICES:
        stats = database.get_device_statistics(device_id, sqlite_path)
        expected = services.calculate_pass_rate(stats["passed_tests"], stats["total_tests"])
        assert oracle.get_device_pass_rate(device_id) == expected


def test_report_view_rows_are_identical(seeded):
    sqlite_path, oracle = seeded
    assert oracle.get_report_rows() == database.get_report_rows(sqlite_path)


def test_exported_csv_and_kpis_are_identical(seeded, tmp_path):
    sqlite_path, oracle = seeded
    from_sqlite, from_oracle = tmp_path / "sqlite.csv", tmp_path / "oracle.csv"
    export_results.write_csv(database.get_report_rows(sqlite_path), from_sqlite)
    export_results.write_csv(oracle.get_report_rows(), from_oracle)
    assert from_oracle.read_bytes() == from_sqlite.read_bytes()
    assert export_results.summarize(oracle.get_report_rows()) == export_results.summarize(
        database.get_report_rows(sqlite_path)
    )


@pytest.mark.parametrize(
    "path",
    [
        "/statistics",
        "/failures",
        "/tests",
        "/tests/250",
        "/devices/FPGA-015/tests",
        "/devices/FPGA-015/statistics",
        "/devices/NOPE/statistics",
    ],
)
def test_api_responses_are_identical(seeded, monkeypatch, path):
    sqlite_path, _ = seeded
    monkeypatch.setattr(config, "DATABASE_PATH", sqlite_path)

    def fetch(backend):
        monkeypatch.setattr(config, "DB_BACKEND", backend)
        with TestClient(app) as client:
            response = client.get(path)
        return response.status_code, response.json()

    assert fetch("oracle") == fetch("sqlite")
