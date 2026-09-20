"""Populate the database with simulated hardware test results.

Run from the project root:

    python -m scripts.generate_test_data
    python -m scripts.generate_test_data --devices 5 --tests-per-device 10 --reset

Each device gets its own small bias (some run hotter, some draw more current),
and every measurement has a small chance of a fault being injected, so the
data contains a realistic mix of PASS and FAIL results.
"""

import argparse
import random
from datetime import datetime, timedelta, timezone

from app import config, database, services

TEST_TYPES = ("POWER", "UART", "MEMORY", "THERMAL", "FUNCTIONAL")
FAULT_PROBABILITY = 0.04  # per measurement


def generate_measurements(rng: random.Random, bias: dict) -> dict:
    """Simulate one test's measurements for a device with the given bias."""
    voltage = rng.gauss(3.3, 0.07)
    current = rng.gauss(0.45 + bias["current"], 0.12)
    temperature = rng.gauss(48 + bias["temperature"], 9)
    duration = rng.uniform(0.5, 5.0)

    if rng.random() < FAULT_PROBABILITY:
        voltage = rng.choice((rng.uniform(2.7, 2.98), rng.uniform(3.62, 3.9)))
    if rng.random() < FAULT_PROBABILITY:
        current = rng.uniform(1.02, 1.4)
    if rng.random() < FAULT_PROBABILITY:
        temperature = rng.uniform(80.5, 98)

    return {
        "voltage": round(voltage, 2),
        "current": round(max(current, 0.0), 2),
        "temperature": round(temperature, 1),
        "duration": round(duration, 2),
    }


def generate(
    devices: int, tests_per_device: int, seed: int | None, db_path: str | None = None
) -> None:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    spread = timedelta(days=30)

    for number in range(1, devices + 1):
        device_id = f"FPGA-{number:03d}"
        bias = {
            "current": rng.uniform(-0.05, 0.15),
            "temperature": rng.uniform(-3, 12),
        }
        for _ in range(tests_per_device):
            measurements = generate_measurements(rng, bias)
            evaluation = services.evaluate_test(**measurements)
            timestamp = now - timedelta(seconds=rng.uniform(0, spread.total_seconds()))
            database.insert_test(
                device_id=device_id,
                test_type=rng.choice(TEST_TYPES),
                result=evaluation.result,
                failure_reason=evaluation.failure_reason,
                timestamp=timestamp.isoformat(timespec="seconds"),
                db_path=db_path,
                **measurements,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--devices", type=int, default=20)
    parser.add_argument("--tests-per-device", type=int, default=25)
    parser.add_argument("--seed", type=int, default=None, help="for reproducible data")
    parser.add_argument("--db", default=config.DATABASE_PATH, help="database file")
    parser.add_argument(
        "--reset", action="store_true", help="delete existing test results first"
    )
    args = parser.parse_args()

    database.init_db(args.db)
    if args.reset:
        with database.get_connection(args.db) as connection:
            connection.execute("DELETE FROM test_results")
    generate(args.devices, args.tests_per_device, args.seed, args.db)

    stats = services.build_statistics(database.get_statistics(args.db))
    print(
        f"Database {args.db}: {stats['total_tests']} tests, "
        f"{stats['passed_tests']} passed, {stats['failed_tests']} failed "
        f"({stats['pass_rate']}% pass rate)"
    )


if __name__ == "__main__":
    main()
