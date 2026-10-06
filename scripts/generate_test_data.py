"""Populate the database with simulated hardware test results.

Run from the project root:

    python -m scripts.generate_test_data
    python -m scripts.generate_test_data --devices 5 --tests-per-device 10 --reset
    python -m scripts.generate_test_data --backend oracle --seed 42 --reset

Each device gets its own small bias (some run hotter, some draw more current),
and every measurement has a small chance of a fault being injected, so the
data contains a realistic mix of PASS and FAIL results.

The same seed and ``--now`` value produce the same rows on either backend.
"""

import argparse
import random
from datetime import datetime, timedelta, timezone

from app import config, repository, services

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


def generate_rows(
    devices: int, tests_per_device: int, seed: int | None, now: datetime | None = None
) -> list[dict]:
    """Build the simulated test results without touching a database.

    ``now`` is the newest possible timestamp; it defaults to the current UTC
    time. Pass a fixed value to make the timestamps reproducible too.
    """
    rng = random.Random(seed)
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    spread = timedelta(days=30)

    rows = []
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
            rows.append(
                {
                    "device_id": device_id,
                    "test_type": rng.choice(TEST_TYPES),
                    "result": evaluation.result,
                    "failure_reason": evaluation.failure_reason,
                    "timestamp": timestamp.isoformat(timespec="seconds"),
                    **measurements,
                }
            )
    return rows


def generate(
    devices: int,
    tests_per_device: int,
    seed: int | None,
    db_path: str | None = None,
    now: datetime | None = None,
    backend=None,
) -> None:
    """Generate the rows and insert them through the chosen backend.

    ``db_path`` only applies to SQLite; ``backend`` defaults to ``DB_BACKEND``.
    """
    backend = backend or repository.get_backend()
    target = {"db_path": db_path} if db_path else {}
    for row in generate_rows(devices, tests_per_device, seed, now):
        backend.insert_test(**row, **target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--devices", type=int, default=20)
    parser.add_argument("--tests-per-device", type=int, default=25)
    parser.add_argument("--seed", type=int, default=None, help="for reproducible data")
    parser.add_argument(
        "--now",
        type=datetime.fromisoformat,
        default=None,
        help="newest timestamp to generate, e.g. 2026-10-01T00:00:00 (default: now, UTC)",
    )
    parser.add_argument(
        "--backend",
        choices=(repository.SQLITE, repository.ORACLE),
        default=config.DB_BACKEND,
        help="database to load (default: DB_BACKEND)",
    )
    parser.add_argument(
        "--db", default=config.DATABASE_PATH, help="SQLite database file (sqlite only)"
    )
    parser.add_argument(
        "--reset", action="store_true", help="delete existing test results first"
    )
    args = parser.parse_args()

    backend = repository.get_backend(args.backend)
    if args.backend == repository.SQLITE:
        target = {"db_path": args.db}
        label = f"Database {args.db}"
    else:
        target = {}
        label = f"Oracle {config.ORACLE_DSN}"

    if args.reset:
        backend.reset_db(**target)
    else:
        backend.init_db(**target)
    generate(
        args.devices, args.tests_per_device, args.seed, target.get("db_path"), args.now, backend
    )

    stats = services.build_statistics(backend.get_statistics(**target))
    print(
        f"{label}: {stats['total_tests']} tests, "
        f"{stats['passed_tests']} passed, {stats['failed_tests']} failed "
        f"({stats['pass_rate']}% pass rate)"
    )


if __name__ == "__main__":
    main()
