import runpy
import sys
from datetime import datetime, timedelta

import pytest

from app import database, repository
from scripts import generate_test_data
from scripts.generate_test_data import generate, generate_rows

NOW = datetime(2026, 10, 1)


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["generate_test_data", *args])
    generate_test_data.main()


def test_rows_are_built_without_a_database():
    rows = generate_rows(devices=3, tests_per_device=4, seed=7, now=NOW)
    assert len(rows) == 12
    assert {row["device_id"] for row in rows} == {"FPGA-001", "FPGA-002", "FPGA-003"}
    assert {row["result"] for row in rows} <= {"PASS", "FAIL"}


def test_rows_are_reproducible_including_timestamps():
    assert generate_rows(4, 5, seed=42, now=NOW) == generate_rows(4, 5, seed=42, now=NOW)


def test_timestamps_fall_in_the_thirty_days_before_now():
    stamps = [datetime.fromisoformat(row["timestamp"]) for row in generate_rows(5, 20, 3, NOW)]
    assert max(stamps) <= NOW
    assert min(stamps) >= NOW - timedelta(days=30)


def test_failed_rows_carry_a_reason_and_passed_rows_do_not():
    for row in generate_rows(20, 25, seed=42, now=NOW):
        assert (row["failure_reason"] is None) == (row["result"] == "PASS")


def test_generate_uses_the_backend_it_is_given(tmp_path):
    db_path = str(tmp_path / "explicit.db")
    database.init_db(db_path)
    generate(2, 3, seed=1, db_path=db_path, now=NOW, backend=database)
    assert len(database.get_all_tests(db_path)) == 6


def test_main_loads_sqlite_and_prints_a_summary(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "cli.db")
    run_main(
        monkeypatch,
        "--devices", "2", "--tests-per-device", "3", "--seed", "1",
        "--backend", "sqlite", "--db", db_path, "--now", "2026-10-01T00:00:00",
    )
    assert len(database.get_all_tests(db_path)) == 6
    assert f"Database {db_path}: 6 tests" in capsys.readouterr().out


def test_main_without_reset_appends(tmp_path, monkeypatch):
    db_path = str(tmp_path / "cli.db")
    args = ("--devices", "1", "--tests-per-device", "2", "--backend", "sqlite", "--db", db_path)
    run_main(monkeypatch, *args)
    run_main(monkeypatch, *args)
    assert [t["id"] for t in database.get_all_tests(db_path)] == [1, 2, 3, 4]


def test_main_with_reset_starts_again(tmp_path, monkeypatch):
    db_path = str(tmp_path / "cli.db")
    args = ("--devices", "1", "--tests-per-device", "2", "--backend", "sqlite", "--db", db_path)
    run_main(monkeypatch, *args)
    run_main(monkeypatch, *args, "--reset")
    assert [t["id"] for t in database.get_all_tests(db_path)] == [1, 2]


class RecordingBackend:
    """Stands in for the Oracle module so the CLI can be checked without a database."""

    def __init__(self):
        self.calls = []
        self.rows = []

    def init_db(self):
        self.calls.append("init_db")

    def reset_db(self):
        self.calls.append("reset_db")

    def insert_test(self, **row):
        self.rows.append(row)

    def get_statistics(self):
        passed = sum(1 for row in self.rows if row["result"] == "PASS")
        return {
            "total_tests": len(self.rows),
            "passed_tests": passed,
            "failed_tests": len(self.rows) - passed,
            "average_voltage": None,
            "average_current": None,
            "average_temperature": None,
        }


@pytest.mark.parametrize(("flag", "expected_call"), [((), "init_db"), (("--reset",), "reset_db")])
def test_main_for_oracle_never_passes_a_sqlite_path(monkeypatch, capsys, flag, expected_call):
    backend = RecordingBackend()
    monkeypatch.setattr(repository, "get_backend", lambda name=None: backend)
    run_main(monkeypatch, "--devices", "2", "--tests-per-device", "2", "--backend", "oracle", *flag)
    assert backend.calls == [expected_call]
    assert len(backend.rows) == 4
    assert all("db_path" not in row for row in backend.rows)
    assert "Oracle " in capsys.readouterr().out


def test_module_runs_as_a_script(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "script.db")
    monkeypatch.setattr(
        sys,
        "argv",
        ["generate_test_data", "--devices", "1", "--tests-per-device", "1", "--db", db_path],
    )
    monkeypatch.delitem(sys.modules, "scripts.generate_test_data")  # run it fresh, as python -m does
    runpy.run_module("scripts.generate_test_data", run_name="__main__")
    assert "1 tests" in capsys.readouterr().out
