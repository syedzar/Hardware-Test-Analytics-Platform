import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app

VALID = {
    "device_id": "FPGA-001",
    "test_type": "POWER",
    "voltage": 3.31,
    "current": 0.42,
    "temperature": 41.7,
    "duration": 2.31,
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A client backed by a throwaway database, so the real one is never touched."""
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "test_api.db"))
    with TestClient(app) as test_client:
        yield test_client


def submit(client, **overrides):
    return client.post("/tests", json={**VALID, **overrides})


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["message"] == "Hardware Test Analytics Platform"


# --- POST /tests -----------------------------------------------------------


def test_create_passing_test(client):
    response = submit(client)
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["result"] == "PASS"
    assert body["failure_reason"] is None
    assert body["timestamp"]


def test_create_failing_test_records_reason(client):
    response = submit(client, temperature=95)
    assert response.status_code == 201
    body = response.json()
    assert body["result"] == "FAIL"
    assert "Temperature above maximum" in body["failure_reason"]


def test_create_records_all_failure_reasons(client):
    body = submit(client, voltage=3.85, current=1.21, temperature=93.0).json()
    assert body["result"] == "FAIL"
    assert body["failure_reason"].count(";") == 2


def test_zero_duration_is_valid_input_but_fails_evaluation(client):
    body = submit(client, duration=0).json()
    assert body["result"] == "FAIL"
    assert "Duration" in body["failure_reason"]


def test_client_cannot_supply_result(client):
    body = submit(client, temperature=100, result="PASS").json()
    assert body["result"] == "FAIL"


@pytest.mark.parametrize(
    "overrides",
    [
        {"voltage": "hello"},
        {"temperature": None},
        {"temperature": "very hot"},
        {"device_id": ""},
        {"device_id": "   "},
        {"duration": -5},
        {"test_type": "NOT_A_TYPE"},
    ],
)
def test_invalid_input_returns_422(client, overrides):
    response = client.post("/tests", json={**VALID, **overrides})
    assert response.status_code == 422


def test_nan_measurement_returns_422(client):
    raw = '{"device_id": "FPGA-001", "test_type": "POWER", "voltage": NaN, ' \
          '"current": 0.4, "temperature": 40, "duration": 2}'
    response = client.post("/tests", content=raw, headers={"Content-Type": "application/json"})
    assert response.status_code == 422


def test_missing_field_returns_422(client):
    body = {k: v for k, v in VALID.items() if k != "current"}
    assert client.post("/tests", json=body).status_code == 422


# --- GET /tests, /tests/{id} ----------------------------------------------


def test_list_tests_empty(client):
    response = client.get("/tests")
    assert response.status_code == 200
    assert response.json() == []


def test_list_tests_returns_all(client):
    submit(client)
    submit(client, device_id="FPGA-002")
    tests = client.get("/tests").json()
    assert [t["device_id"] for t in tests] == ["FPGA-001", "FPGA-002"]


def test_get_one_test(client):
    created = submit(client).json()
    response = client.get(f"/tests/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_test_returns_404(client):
    assert client.get("/tests/999999").status_code == 404


def test_non_integer_id_returns_422(client):
    assert client.get("/tests/abc").status_code == 422


# --- DELETE /tests/{id} ----------------------------------------------------


def test_delete_test(client):
    test_id = submit(client).json()["id"]
    assert client.delete(f"/tests/{test_id}").status_code == 204
    assert client.get(f"/tests/{test_id}").status_code == 404


def test_delete_missing_test_returns_404(client):
    assert client.delete("/tests/999999").status_code == 404


# --- Filtering -------------------------------------------------------------


def test_failures_returns_only_failed_tests(client):
    submit(client)
    submit(client, temperature=95)
    submit(client, voltage=2.5)
    failures = client.get("/failures").json()
    assert len(failures) == 2
    assert {t["result"] for t in failures} == {"FAIL"}


def test_device_tests_returns_only_that_device(client):
    submit(client, device_id="FPGA-001")
    submit(client, device_id="FPGA-002")
    submit(client, device_id="FPGA-001", test_type="UART")
    tests = client.get("/devices/FPGA-001/tests").json()
    assert [t["test_type"] for t in tests] == ["POWER", "UART"]


def test_device_tests_for_unknown_device_is_empty_list(client):
    response = client.get("/devices/NOPE/tests")
    assert response.status_code == 200
    assert response.json() == []


# --- Statistics ------------------------------------------------------------


def test_overall_statistics(client):
    submit(client, voltage=3.2, current=0.4, temperature=40.0)
    submit(client, voltage=3.4, current=0.6, temperature=50.0)
    submit(client, voltage=3.3, current=0.5, temperature=90.0)
    submit(client, voltage=3.3, current=0.5, temperature=60.0)
    stats = client.get("/statistics").json()
    assert stats["total_tests"] == 4
    assert stats["passed_tests"] == 3
    assert stats["failed_tests"] == 1
    assert stats["pass_rate"] == 75.0
    assert stats["average_voltage"] == 3.3
    assert stats["average_current"] == 0.5
    assert stats["average_temperature"] == 60.0


def test_overall_statistics_when_empty(client):
    stats = client.get("/statistics").json()
    assert stats["total_tests"] == 0
    assert stats["pass_rate"] == 0.0
    assert stats["average_voltage"] is None


def test_device_statistics(client):
    for _ in range(3):
        submit(client, device_id="FPGA-008")
    submit(client, device_id="FPGA-008", temperature=95)
    submit(client, device_id="FPGA-009")
    stats = client.get("/devices/FPGA-008/statistics").json()
    assert stats["device_id"] == "FPGA-008"
    assert stats["total_tests"] == 4
    assert stats["passed_tests"] == 3
    assert stats["failed_tests"] == 1
    assert stats["pass_rate"] == 75.0


def test_device_statistics_for_unknown_device_returns_404(client):
    assert client.get("/devices/NOPE/statistics").status_code == 404


# --- Persistence -----------------------------------------------------------


def test_data_persists_across_app_restarts(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "persist.db"))
    with TestClient(app) as first:
        first.post("/tests", json=VALID)
    with TestClient(app) as second:
        assert len(second.get("/tests").json()) == 1
