"""Export the flat reporting view to a CSV for Power BI and Tableau.

Run from the project root:

    python -m bi.export_results
    python -m bi.export_results --backend oracle
    python -m bi.export_results --out my_results.csv --kpis my_kpis.json

The rows come from the ``v_test_report`` view of the chosen backend. A small
JSON file of KPI values is written next to the CSV; the dashboard build
guides quote it, so a finished dashboard can be checked against it.
"""

import argparse
import csv
import json
from pathlib import Path

from app import config, repository, services
from app.database import REPORT_COLUMNS

DEFAULT_OUT = Path("bi/data/test_results.csv")
DEFAULT_KPIS = Path("bi/data/kpi_summary.json")
FAULT_COLUMNS = ("voltage_fault", "current_fault", "temperature_fault", "duration_fault")


def write_csv(rows: list[dict], out_path: Path) -> None:
    """Write the report rows with a header; a missing failure reason is left blank."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _group(rows: list[dict], key: str) -> list[dict]:
    """Tests, failures and pass rate for each value of ``key``, sorted by that value."""
    groups: dict[str, dict] = {}
    for row in rows:
        group = groups.setdefault(row[key], {"total_tests": 0, "failed_tests": 0})
        group["total_tests"] += 1
        group["failed_tests"] += row["failed"]
    return [
        {
            key: value,
            **group,
            "pass_rate": services.calculate_pass_rate(
                group["total_tests"] - group["failed_tests"], group["total_tests"]
            ),
        }
        for value, group in sorted(groups.items())
    ]


def _average(rows: list[dict], column: str) -> float | None:
    if not rows:
        return None
    return round(sum(row[column] for row in rows) / len(rows), 2)


def summarize(rows: list[dict]) -> dict:
    """Work out the KPI values a dashboard built on these rows should show."""
    total = len(rows)
    failed = sum(row["failed"] for row in rows)
    devices = _group(rows, "device_id")
    lowest = min((device["pass_rate"] for device in devices), default=None)
    dates = sorted(row["test_date"] for row in rows)
    return {
        "total_tests": total,
        "passed_tests": total - failed,
        "failure_count": failed,
        "pass_rate": services.calculate_pass_rate(total - failed, total),
        "devices_tested": len(devices),
        "devices_with_failures": sum(1 for device in devices if device["failed_tests"]),
        "worst_devices": [d["device_id"] for d in devices if d["pass_rate"] == lowest],
        "worst_device_pass_rate": lowest,
        "fault_counts": {column: sum(row[column] for row in rows) for column in FAULT_COLUMNS},
        "average_voltage_v": _average(rows, "voltage_v"),
        "average_current_a": _average(rows, "current_a"),
        "average_temperature_c": _average(rows, "temperature_c"),
        "first_test_date": dates[0] if dates else None,
        "last_test_date": dates[-1] if dates else None,
        "by_device": devices,
        "by_test_type": _group(rows, "test_type"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--backend",
        choices=(repository.SQLITE, repository.ORACLE),
        default=config.DB_BACKEND,
        help="database to read (default: DB_BACKEND)",
    )
    parser.add_argument(
        "--db", default=config.DATABASE_PATH, help="SQLite database file (sqlite only)"
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="CSV file to write")
    parser.add_argument("--kpis", type=Path, default=DEFAULT_KPIS, help="KPI JSON file to write")
    args = parser.parse_args()

    backend = repository.get_backend(args.backend)
    target = {"db_path": args.db} if args.backend == repository.SQLITE else {}
    rows = backend.get_report_rows(**target)

    write_csv(rows, args.out)
    summary = summarize(rows)
    args.kpis.parent.mkdir(parents=True, exist_ok=True)
    args.kpis.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(
        f"Wrote {len(rows)} rows to {args.out} ({args.backend}): "
        f"{summary['pass_rate']}% pass rate, {summary['failure_count']} failures, "
        f"{summary['devices_with_failures']} of {summary['devices_tested']} devices with failures"
    )


if __name__ == "__main__":
    main()
