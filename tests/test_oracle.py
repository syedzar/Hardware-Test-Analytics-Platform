"""Tests for the Oracle backend and the PL/SQL package.

They need a running Oracle database (``docker compose up -d oracle``) and are
skipped when there is none. Each test starts from an empty, rebuilt schema.
"""

import pytest
from fastapi.testclient import TestClient

from app import schemas
from app.main import app

FAIL_REASON = "Temperature above maximum limit (95.0 C > 80.0 C)"

VALID = {
    "device_id": "FPGA-001",
    "test_type": "POWER",
    "voltage": 3.31,
    "current": 0.42,
    "temperature": 41.7,
    "duration": 2.31,
}


def add(oracle, device_id="FPGA-001", result="PASS", **overrides):
    values = dict(
        device_id=device_id,
        test_type="POWER",
        voltage=3.3,
        current=0.4,
        temperature=45.0,
        duration=2.0,
        result=result,
        failure_reason=None if result == "PASS" else FAIL_REASON,
    )
    values.update(overrides)
    return oracle.insert_test(**values)


def query(oracle, sql, **binds):
    with oracle.get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, binds)
            return cursor.fetchall()


# --- Schema ----------------------------------------------------------------


def test_init_db_is_idempotent(oracle):
    add(oracle)
    oracle.init_db()
    assert len(oracle.get_all_tests()) == 1


def test_reset_db_removes_tests_and_restarts_ids(oracle):
    add(oracle)
    add(oracle)
    oracle.reset_db()
    assert oracle.get_all_tests() == []
    assert add(oracle)["id"] == 1


def test_test_type_lookup_matches_the_api_enum(oracle):
    rows = query(oracle, "SELECT type_code FROM test_types")
    assert {row[0] for row in rows} == {test_type.value for test_type in schemas.TestType}


def test_package_and_views_are_valid(oracle):
    rows = query(
        oracle,
        "SELECT object_name, object_type, status FROM user_objects "
        "WHERE object_type IN ('PACKAGE', 'PACKAGE BODY', 'VIEW')",
    )
    assert {(name, kind) for name, kind, _ in rows} == {
        ("TEST_STATS_PKG", "PACKAGE"),
        ("TEST_STATS_PKG", "PACKAGE BODY"),
        ("V_TEST_REPORT", "VIEW"),
        ("V_FAILED_TESTS", "VIEW"),
    }
    assert {status for _, _, status in rows} == {"VALID"}


def test_a_package_that_does_not_compile_is_reported(oracle, tmp_path, monkeypatch):
    (tmp_path / "broken.sql").write_text(
        "CREATE OR REPLACE PACKAGE test_stats_pkg AS\n    this is not plsql\nEND;\n/\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(oracle, "SQL_DIR", tmp_path)
    monkeypatch.setattr(oracle, "SCHEMA_FILES", ("broken.sql",))
    with pytest.raises(RuntimeError, match="test_stats_pkg did not compile"):
        oracle.init_db()


# --- record_test_result ----------------------------------------------------


def test_insert_returns_stored_record(oracle):
    record = add(oracle)
    assert record["id"] == 1
    assert record["device_id"] == "FPGA-001"
    assert record["test_type"] == "POWER"
    assert (record["voltage"], record["current"]) == (3.3, 0.4)
    assert (record["temperature"], record["duration"]) == (45.0, 2.0)
    assert record["result"] == "PASS"
    assert record["failure_reason"] is None
    assert "T" in record["timestamp"]


def test_insert_keeps_a_supplied_timestamp(oracle):
    assert add(oracle, timestamp="2026-09-14T08:30:05")["timestamp"] == "2026-09-14T08:30:05"


def test_measurements_round_trip_exactly(oracle):
    record = add(oracle, voltage=3.3123456789, current=0.1, temperature=-12.5)
    assert record["voltage"] == 3.3123456789
    assert record["current"] == 0.1
    assert record["temperature"] == -12.5


def test_a_device_is_registered_once(oracle):
    add(oracle, device_id="FPGA-001")
    add(oracle, device_id="FPGA-001")
    add(oracle, device_id="FPGA-002")
    assert query(oracle, "SELECT COUNT(*) FROM devices") == [(2,)]
    assert query(oracle, "SELECT COUNT(*) FROM test_results") == [(3,)]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"device_id": ""}, "ORA-20001: Device code must be 1 to 64 characters"),
        ({"device_id": "x" * 65}, "ORA-20001: Device code must be 1 to 64 characters"),
        ({"test_type": "NOT_A_TYPE"}, "ORA-20002: Unknown test type: NOT_A_TYPE"),
        ({"result": "MAYBE"}, "ORA-20003: Result must be PASS or FAIL"),
        (
            {"result": "FAIL", "failure_reason": None},
            "ORA-20003: A FAIL result needs a failure reason",
        ),
        ({"failure_reason": "x"}, "ORA-20003: A PASS result cannot have a failure reason"),
        ({"voltage": float("nan")}, "ORA-20004: Measurements must be finite numbers"),
        ({"temperature": float("inf")}, "ORA-20004: Measurements must be finite numbers"),
        ({"duration": -1.0}, "ORA-20004: Duration cannot be negative"),
    ],
)
def test_procedure_rejects_invalid_values(oracle, overrides, message):
    with pytest.raises(ValueError) as error:
        add(oracle, **overrides)
    assert str(error.value) == message
    assert oracle.get_all_tests() == []


def test_a_failed_insert_leaves_no_device_behind(oracle):
    import oracledb

    with pytest.raises(oracledb.DatabaseError, match="ORA-12899"):  # value too large
        add(oracle, device_id="FPGA-777", result="FAIL", failure_reason="x" * 501)
    assert query(oracle, "SELECT COUNT(*) FROM devices") == [(0,)]


# --- Constraints hold even when the package is bypassed ---------------------


def test_check_constraint_rejects_an_unknown_result(oracle):
    import oracledb

    add(oracle)
    with pytest.raises(oracledb.IntegrityError, match="ORA-02290"):  # check constraint violated
        query(oracle, "UPDATE test_results SET result = 'SKIP'")


def test_check_constraint_ties_the_failure_reason_to_the_result(oracle):
    import oracledb

    add(oracle)
    with pytest.raises(oracledb.IntegrityError, match="CK_RESULTS_REASON"):
        query(oracle, "UPDATE test_results SET result = 'FAIL'")


def test_foreign_key_rejects_an_unknown_device(oracle):
    import oracledb

    add(oracle)
    with pytest.raises(oracledb.IntegrityError, match="FK_RESULTS_DEVICE"):
        query(oracle, "UPDATE test_results SET device_id = :device_id", device_id=999999)


def test_views_are_read_only(oracle):
    import oracledb

    add(oracle)
    with pytest.raises(oracledb.DatabaseError, match="ORA-42399"):
        query(oracle, "DELETE FROM v_test_report")


# --- Reads -----------------------------------------------------------------


def test_get_test_by_id(oracle):
    created = add(oracle)
    assert oracle.get_test(created["id"]) == created


def test_get_missing_test_returns_none(oracle):
    assert oracle.get_test(999) is None


def test_get_all_tests_returns_every_record(oracle):
    for _ in range(3):
        add(oracle)
    assert [t["id"] for t in oracle.get_all_tests()] == [1, 2, 3]


def test_get_device_tests_filters_by_device(oracle):
    add(oracle, device_id="FPGA-001")
    add(oracle, device_id="FPGA-002")
    add(oracle, device_id="FPGA-001")
    tests = oracle.get_device_tests("FPGA-001")
    assert len(tests) == 2
    assert {t["device_id"] for t in tests} == {"FPGA-001"}


def test_failed_tests_come_from_the_failures_view(oracle):
    add(oracle, result="PASS")
    add(oracle, result="FAIL")
    add(oracle, result="FAIL")
    failures = oracle.get_failed_tests()
    assert len(failures) == 2
    assert {t["result"] for t in failures} == {"FAIL"}
    assert query(oracle, "SELECT COUNT(*) FROM v_failed_tests") == [(2,)]


def test_sql_injection_attempt_is_treated_as_data(oracle):
    add(oracle, device_id="FPGA-001")
    assert oracle.get_device_tests("x' OR '1'='1") == []
    stored = add(oracle, device_id="x'; DROP TABLE test_results; --")
    assert stored["device_id"] == "x'; DROP TABLE test_results; --"
    assert len(oracle.get_all_tests()) == 2


def test_delete_test(oracle):
    created = add(oracle)
    assert oracle.delete_test(created["id"]) is True
    assert oracle.get_test(created["id"]) is None


def test_delete_missing_test_returns_false(oracle):
    assert oracle.delete_test(999) is False


def test_report_row_flags_each_kind_of_fault(oracle):
    add(
        oracle,
        voltage=3.85,
        temperature=93.0,
        result="FAIL",
        failure_reason=(
            "Voltage above maximum limit (3.85 V > 3.6 V); "
            "Temperature above maximum limit (93.0 C > 80.0 C)"
        ),
        timestamp="2026-09-14T08:30:00",
    )
    (row,) = oracle.get_report_rows()
    assert (row["passed"], row["failed"]) == (0, 1)
    assert (row["voltage_fault"], row["current_fault"]) == (1, 0)
    assert (row["temperature_fault"], row["duration_fault"]) == (1, 0)
    assert (row["tested_at"], row["test_date"]) == ("2026-09-14T08:30:00", "2026-09-14")


# --- Statistics through the package ----------------------------------------


def test_statistics(oracle):
    add(oracle, result="PASS", voltage=3.2, current=0.4, temperature=40.0)
    add(oracle, result="PASS", voltage=3.4, current=0.6, temperature=50.0)
    add(oracle, result="FAIL", voltage=3.3, current=0.5, temperature=90.0)
    stats = oracle.get_statistics()
    assert stats["total_tests"] == 3
    assert stats["passed_tests"] == 2
    assert stats["failed_tests"] == 1
    assert stats["average_voltage"] == pytest.approx(3.3)
    assert stats["average_current"] == pytest.approx(0.5)
    assert stats["average_temperature"] == pytest.approx(60.0)


def test_statistics_on_empty_database(oracle):
    stats = oracle.get_statistics()
    assert stats["total_tests"] == 0
    assert stats["passed_tests"] == 0
    assert stats["failed_tests"] == 0
    assert stats["average_voltage"] is None
    assert oracle.get_statistics_by_device() == []


def test_device_statistics_only_count_that_device(oracle):
    add(oracle, device_id="FPGA-001", result="PASS")
    add(oracle, device_id="FPGA-001", result="FAIL")
    add(oracle, device_id="FPGA-002", result="PASS")
    stats = oracle.get_device_statistics("FPGA-001")
    assert stats["total_tests"] == 2
    assert stats["passed_tests"] == 1
    assert stats["failed_tests"] == 1


def test_device_statistics_for_unknown_device_are_zero(oracle):
    add(oracle)
    stats = oracle.get_device_statistics("NOPE")
    assert stats["total_tests"] == 0
    assert stats["average_voltage"] is None


def test_per_device_ref_cursor_has_one_row_per_device(oracle):
    add(oracle, device_id="FPGA-002", result="PASS")
    add(oracle, device_id="FPGA-001", result="PASS")
    add(oracle, device_id="FPGA-001", result="FAIL")
    add(oracle, device_id="FPGA-001", result="FAIL")
    first, second = oracle.get_statistics_by_device()
    assert (first["device_id"], first["total_tests"], first["failed_tests"]) == ("FPGA-001", 3, 2)
    assert first["pass_rate"] == 33.3
    assert (second["device_id"], second["pass_rate"]) == ("FPGA-002", 100.0)


def test_device_pass_rate_function(oracle):
    add(oracle, device_id="FPGA-001", result="PASS")
    add(oracle, device_id="FPGA-001", result="PASS")
    add(oracle, device_id="FPGA-001", result="FAIL")
    assert oracle.get_device_pass_rate("FPGA-001") == 66.7
    assert oracle.get_device_pass_rate("NOPE") is None


# --- The same API, served from Oracle ---------------------------------------


@pytest.fixture
def client(oracle):
    with TestClient(app) as test_client:
        yield test_client


def test_api_creates_and_reads_a_test(client):
    response = client.post("/tests", json=VALID)
    assert response.status_code == 201
    created = response.json()
    assert created["id"] == 1
    assert created["result"] == "PASS"
    assert client.get("/tests/1").json() == created
    assert client.get("/tests").json() == [created]


def test_api_records_failure_reasons(client):
    body = client.post("/tests", json={**VALID, "voltage": 3.85, "temperature": 93.0}).json()
    assert body["result"] == "FAIL"
    assert body["failure_reason"].count(";") == 1
    assert client.get("/failures").json() == [body]


def test_api_rejects_invalid_input_before_the_database(client):
    assert client.post("/tests", json={**VALID, "test_type": "NOT_A_TYPE"}).status_code == 422
    assert client.get("/tests").json() == []


def test_api_deletes_a_test(client):
    client.post("/tests", json=VALID)
    assert client.delete("/tests/1").status_code == 204
    assert client.get("/tests/1").status_code == 404
    assert client.delete("/tests/1").status_code == 404


def test_api_filters_by_device(client):
    client.post("/tests", json=VALID)
    client.post("/tests", json={**VALID, "device_id": "FPGA-002"})
    assert [t["device_id"] for t in client.get("/devices/FPGA-002/tests").json()] == ["FPGA-002"]
    assert client.get("/devices/NOPE/tests").json() == []


def test_api_statistics(client):
    for temperature in (40.0, 50.0, 90.0, 60.0):
        client.post("/tests", json={**VALID, "voltage": 3.3, "current": 0.5, "temperature": temperature})
    stats = client.get("/statistics").json()
    assert stats == {
        "total_tests": 4,
        "passed_tests": 3,
        "failed_tests": 1,
        "pass_rate": 75.0,
        "average_voltage": 3.3,
        "average_current": 0.5,
        "average_temperature": 60.0,
    }
    assert client.get("/devices/FPGA-001/statistics").json() == {"device_id": "FPGA-001", **stats}
    assert client.get("/devices/NOPE/statistics").status_code == 404


def test_api_data_persists_across_app_restarts(oracle):
    with TestClient(app) as first:
        first.post("/tests", json=VALID)
    with TestClient(app) as second:
        assert len(second.get("/tests").json()) == 1
