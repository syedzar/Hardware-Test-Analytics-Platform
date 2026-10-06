import pytest

from app import database

FAIL_REASON = (
    "Voltage above maximum limit (3.85 V > 3.6 V); "
    "Temperature above maximum limit (93.0 C > 80.0 C)"
)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_reporting.db")
    database.init_db(path)
    return path


def add(db_path, **overrides):
    values = dict(
        device_id="FPGA-001",
        test_type="POWER",
        voltage=3.3,
        current=0.4,
        temperature=45.0,
        duration=2.0,
        result="PASS",
        failure_reason=None,
        timestamp="2026-09-14T08:30:00",
        db_path=db_path,
    )
    values.update(overrides)
    return database.insert_test(**values)


def test_report_rows_have_the_report_columns(db_path):
    add(db_path)
    (row,) = database.get_report_rows(db_path)
    assert tuple(row) == database.REPORT_COLUMNS


def test_report_row_for_a_passing_test(db_path):
    add(db_path)
    (row,) = database.get_report_rows(db_path)
    assert row["result_id"] == 1
    assert row["device_id"] == "FPGA-001"
    assert row["test_type"] == "POWER"
    assert (row["passed"], row["failed"]) == (1, 0)
    assert (row["voltage_v"], row["current_a"]) == (3.3, 0.4)
    assert (row["temperature_c"], row["duration_s"]) == (45.0, 2.0)
    assert row["failure_reason"] is None
    assert row["tested_at"] == "2026-09-14T08:30:00"
    assert row["test_date"] == "2026-09-14"
    assert [row[c] for c in database.REPORT_COLUMNS if c.endswith("_fault")] == [0, 0, 0, 0]


def test_report_row_flags_each_kind_of_fault(db_path):
    add(db_path, voltage=3.85, temperature=93.0, result="FAIL", failure_reason=FAIL_REASON)
    (row,) = database.get_report_rows(db_path)
    assert (row["passed"], row["failed"]) == (0, 1)
    assert row["voltage_fault"] == 1
    assert row["current_fault"] == 0
    assert row["temperature_fault"] == 1
    assert row["duration_fault"] == 0


def test_report_rows_are_ordered_by_result_id(db_path):
    for _ in range(3):
        add(db_path)
    assert [row["result_id"] for row in database.get_report_rows(db_path)] == [1, 2, 3]


def test_reset_db_removes_tests_and_restarts_ids(db_path):
    add(db_path)
    add(db_path)
    database.reset_db(db_path)
    assert database.get_all_tests(db_path) == []
    assert add(db_path)["id"] == 1
