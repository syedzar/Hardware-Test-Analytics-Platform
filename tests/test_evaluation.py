import pytest

from app.services import FAIL, PASS, calculate_pass_rate, evaluate_test

NOMINAL = dict(voltage=3.3, current=0.4, temperature=45.0, duration=2.0)


def evaluate(**overrides):
    return evaluate_test(**{**NOMINAL, **overrides})


def test_normal_measurements_pass():
    evaluation = evaluate()
    assert evaluation.result == PASS
    assert evaluation.failure_reason is None


def test_high_temperature_fails():
    evaluation = evaluate(temperature=95)
    assert evaluation.result == FAIL
    assert "Temperature above maximum" in evaluation.failure_reason


def test_high_voltage_fails():
    evaluation = evaluate(voltage=3.85)
    assert evaluation.result == FAIL
    assert "Voltage above maximum" in evaluation.failure_reason


def test_low_voltage_fails():
    evaluation = evaluate(voltage=2.8)
    assert evaluation.result == FAIL
    assert "Voltage below minimum" in evaluation.failure_reason


def test_high_current_fails():
    evaluation = evaluate(current=1.21)
    assert evaluation.result == FAIL
    assert "Current above maximum" in evaluation.failure_reason


@pytest.mark.parametrize("duration", [0, -1.5])
def test_non_positive_duration_fails(duration):
    evaluation = evaluate(duration=duration)
    assert evaluation.result == FAIL
    assert "Duration" in evaluation.failure_reason


def test_multiple_failures_record_every_reason():
    evaluation = evaluate(voltage=3.85, current=1.21, temperature=93.0)
    assert evaluation.result == FAIL
    assert len(evaluation.failure_reasons) == 3
    assert evaluation.failure_reason.count(";") == 2


@pytest.mark.parametrize(
    "field, value, expected",
    [
        ("voltage", 3.59, PASS),
        ("voltage", 3.60, PASS),
        ("voltage", 3.61, FAIL),
        ("voltage", 3.01, PASS),
        ("voltage", 3.00, PASS),
        ("voltage", 2.99, FAIL),
        ("current", 1.0, PASS),
        ("current", 1.01, FAIL),
        ("temperature", 79.9, PASS),
        ("temperature", 80.0, PASS),
        ("temperature", 80.1, FAIL),
        ("duration", 0.001, PASS),
        ("duration", 0.0, FAIL),
    ],
)
def test_boundaries(field, value, expected):
    assert evaluate(**{field: value}).result == expected


def test_pass_rate():
    assert calculate_pass_rate(463, 500) == 92.6
    assert calculate_pass_rate(21, 25) == 84.0


def test_pass_rate_with_no_tests_is_zero():
    assert calculate_pass_rate(0, 0) == 0.0
