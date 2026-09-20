"""Business logic: engineering evaluation and statistics helpers.

Nothing in this module knows about FastAPI or SQLite, so it can be tested
and reused on its own.
"""

from dataclasses import dataclass

from app import config

PASS = "PASS"
FAIL = "FAIL"


@dataclass(frozen=True)
class Evaluation:
    """Outcome of evaluating one set of measurements."""

    result: str
    failure_reasons: tuple[str, ...] = ()

    @property
    def failure_reason(self) -> str | None:
        """All failure reasons joined into one string, or None when passing."""
        if not self.failure_reasons:
            return None
        return "; ".join(self.failure_reasons)


def check_voltage(voltage: float) -> str | None:
    if voltage < config.MIN_VOLTAGE:
        return f"Voltage below minimum limit ({voltage} V < {config.MIN_VOLTAGE} V)"
    if voltage > config.MAX_VOLTAGE:
        return f"Voltage above maximum limit ({voltage} V > {config.MAX_VOLTAGE} V)"
    return None


def check_current(current: float) -> str | None:
    if current > config.MAX_CURRENT:
        return f"Current above maximum limit ({current} A > {config.MAX_CURRENT} A)"
    return None


def check_temperature(temperature: float) -> str | None:
    if temperature > config.MAX_TEMPERATURE:
        return (
            f"Temperature above maximum limit "
            f"({temperature} C > {config.MAX_TEMPERATURE} C)"
        )
    return None


def check_duration(duration: float) -> str | None:
    if duration <= config.MIN_DURATION_EXCLUSIVE:
        return f"Duration must be greater than {config.MIN_DURATION_EXCLUSIVE} seconds"
    return None


def evaluate_test(
    voltage: float, current: float, temperature: float, duration: float
) -> Evaluation:
    """Decide PASS or FAIL for one test, collecting every failure reason."""
    checks = (
        check_voltage(voltage),
        check_current(current),
        check_temperature(temperature),
        check_duration(duration),
    )
    reasons = tuple(reason for reason in checks if reason is not None)
    return Evaluation(FAIL if reasons else PASS, reasons)


def calculate_pass_rate(passed_tests: int, total_tests: int) -> float:
    """Pass rate as a percentage rounded to one decimal; 0.0 with no tests."""
    if total_tests == 0:
        return 0.0
    return round(passed_tests / total_tests * 100, 1)


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def build_statistics(row: dict) -> dict:
    """Turn raw aggregate values from the database into the API statistics shape."""
    return {
        "total_tests": row["total_tests"],
        "passed_tests": row["passed_tests"],
        "failed_tests": row["failed_tests"],
        "pass_rate": calculate_pass_rate(row["passed_tests"], row["total_tests"]),
        "average_voltage": _round_or_none(row["average_voltage"]),
        "average_current": _round_or_none(row["average_current"]),
        "average_temperature": _round_or_none(row["average_temperature"]),
    }
