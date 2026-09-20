import pytest

from app import database


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_database.db")
    database.init_db(path)
    return path


def add(db_path, device_id="FPGA-001", result="PASS", **overrides):
    values = dict(
        device_id=device_id,
        test_type="POWER",
        voltage=3.3,
        current=0.4,
        temperature=45.0,
        duration=2.0,
        result=result,
        failure_reason=None if result == "PASS" else "Temperature above maximum limit",
        db_path=db_path,
    )
    values.update(overrides)
    return database.insert_test(**values)


def test_init_db_is_idempotent(db_path):
    database.init_db(db_path)
    assert database.get_all_tests(db_path) == []


def test_insert_returns_stored_record(db_path):
    record = add(db_path)
    assert record["id"] == 1
    assert record["device_id"] == "FPGA-001"
    assert record["result"] == "PASS"
    assert record["failure_reason"] is None
    assert "T" in record["timestamp"]


def test_get_test_by_id(db_path):
    created = add(db_path)
    assert database.get_test(created["id"], db_path) == created


def test_get_missing_test_returns_none(db_path):
    assert database.get_test(999, db_path) is None


def test_get_all_tests_returns_every_record(db_path):
    for _ in range(3):
        add(db_path)
    assert [t["id"] for t in database.get_all_tests(db_path)] == [1, 2, 3]


def test_get_device_tests_filters_by_device(db_path):
    add(db_path, device_id="FPGA-001")
    add(db_path, device_id="FPGA-002")
    add(db_path, device_id="FPGA-001")
    tests = database.get_device_tests("FPGA-001", db_path)
    assert len(tests) == 2
    assert {t["device_id"] for t in tests} == {"FPGA-001"}


def test_failed_tests_are_filtered(db_path):
    add(db_path, result="PASS")
    add(db_path, result="FAIL")
    add(db_path, result="FAIL")
    failures = database.get_failed_tests(db_path)
    assert len(failures) == 2
    assert {t["result"] for t in failures} == {"FAIL"}


def test_delete_test(db_path):
    created = add(db_path)
    assert database.delete_test(created["id"], db_path) is True
    assert database.get_test(created["id"], db_path) is None


def test_delete_missing_test_returns_false(db_path):
    assert database.delete_test(999, db_path) is False


def test_statistics(db_path):
    add(db_path, result="PASS", voltage=3.2, current=0.4, temperature=40.0)
    add(db_path, result="PASS", voltage=3.4, current=0.6, temperature=50.0)
    add(db_path, result="FAIL", voltage=3.3, current=0.5, temperature=90.0)
    stats = database.get_statistics(db_path)
    assert stats["total_tests"] == 3
    assert stats["passed_tests"] == 2
    assert stats["failed_tests"] == 1
    assert stats["average_voltage"] == pytest.approx(3.3)
    assert stats["average_current"] == pytest.approx(0.5)
    assert stats["average_temperature"] == pytest.approx(60.0)


def test_device_statistics_only_count_that_device(db_path):
    add(db_path, device_id="FPGA-001", result="PASS")
    add(db_path, device_id="FPGA-001", result="FAIL")
    add(db_path, device_id="FPGA-002", result="PASS")
    stats = database.get_device_statistics("FPGA-001", db_path)
    assert stats["total_tests"] == 2
    assert stats["passed_tests"] == 1
    assert stats["failed_tests"] == 1


def test_statistics_on_empty_database(db_path):
    stats = database.get_statistics(db_path)
    assert stats["total_tests"] == 0
    assert stats["passed_tests"] == 0
    assert stats["average_voltage"] is None


def test_sql_injection_attempt_is_treated_as_data(db_path):
    add(db_path, device_id="FPGA-001")
    assert database.get_device_tests("x' OR '1'='1", db_path) == []
    assert len(database.get_all_tests(db_path)) == 1
