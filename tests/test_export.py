import csv
import json
import runpy
import sys
from datetime import datetime
from pathlib import Path

import pytest

from app import database
from bi import export_results
from scripts.generate_test_data import generate

BI_DATA = Path(__file__).resolve().parent.parent / "bi" / "data"


def seeded_rows(tmp_path, devices=20, tests_per_device=25):
    """The dataset the committed CSV was built from: seed 42, anchored at 2026-10-01."""
    db_path = str(tmp_path / "export.db")
    database.init_db(db_path)
    generate(devices, tests_per_device, seed=42, db_path=db_path, now=datetime(2026, 10, 1))
    return db_path, database.get_report_rows(db_path)


def report_row(result_id, device_id, failed, **overrides):
    row = dict.fromkeys(database.REPORT_COLUMNS, 0)
    row.update(
        result_id=result_id,
        device_id=device_id,
        test_type="POWER",
        result="FAIL" if failed else "PASS",
        passed=1 - failed,
        failed=failed,
        voltage_v=3.3,
        current_a=0.5,
        temperature_c=50.0,
        duration_s=2.0,
        failure_reason="Current above maximum limit" if failed else None,
        current_fault=failed,
        tested_at="2026-09-14T08:30:00",
        test_date="2026-09-14",
    )
    row.update(overrides)
    return row


def test_csv_has_a_header_and_one_line_per_row(tmp_path):
    out = tmp_path / "nested" / "out.csv"
    export_results.write_csv([report_row(1, "FPGA-001", 0), report_row(2, "FPGA-001", 1)], out)
    with out.open(newline="", encoding="utf-8") as handle:
        lines = list(csv.reader(handle))
    assert tuple(lines[0]) == database.REPORT_COLUMNS
    assert len(lines) == 3


def test_csv_leaves_a_missing_failure_reason_blank(tmp_path):
    out = tmp_path / "out.csv"
    export_results.write_csv([report_row(1, "FPGA-001", 0)], out)
    with out.open(newline="", encoding="utf-8") as handle:
        (row,) = list(csv.DictReader(handle))
    assert row["failure_reason"] == ""
    assert row["passed"] == "1"


def test_summary_of_a_small_dataset():
    rows = [
        report_row(1, "FPGA-001", 0),
        report_row(2, "FPGA-001", 1, test_date="2026-09-20"),
        report_row(3, "FPGA-002", 0, test_type="UART", test_date="2026-09-10"),
        report_row(4, "FPGA-002", 0, temperature_c=60.0),
    ]
    summary = export_results.summarize(rows)
    assert summary["total_tests"] == 4
    assert summary["passed_tests"] == 3
    assert summary["failure_count"] == 1
    assert summary["pass_rate"] == 75.0
    assert summary["devices_tested"] == 2
    assert summary["devices_with_failures"] == 1
    assert summary["worst_devices"] == ["FPGA-001"]
    assert summary["worst_device_pass_rate"] == 50.0
    assert summary["fault_counts"]["current_fault"] == 1
    assert summary["average_temperature_c"] == 52.5
    assert (summary["first_test_date"], summary["last_test_date"]) == ("2026-09-10", "2026-09-20")
    assert summary["by_test_type"] == [
        {"test_type": "POWER", "total_tests": 3, "failed_tests": 1, "pass_rate": 66.7},
        {"test_type": "UART", "total_tests": 1, "failed_tests": 0, "pass_rate": 100.0},
    ]


def test_summary_lists_every_device_tied_for_worst():
    rows = [report_row(1, "FPGA-002", 1), report_row(2, "FPGA-001", 1), report_row(3, "FPGA-003", 0)]
    assert export_results.summarize(rows)["worst_devices"] == ["FPGA-001", "FPGA-002"]


def test_summary_of_no_rows():
    summary = export_results.summarize([])
    assert summary["total_tests"] == 0
    assert summary["pass_rate"] == 0.0
    assert summary["worst_devices"] == []
    assert summary["worst_device_pass_rate"] is None
    assert summary["average_voltage_v"] is None
    assert summary["first_test_date"] is None


def test_main_writes_the_csv_and_the_kpi_file(tmp_path, monkeypatch, capsys):
    db_path, rows = seeded_rows(tmp_path, devices=3, tests_per_device=4)
    out, kpis = tmp_path / "out.csv", tmp_path / "kpis" / "kpis.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["export_results", "--backend", "sqlite", "--db", db_path, "--out", str(out), "--kpis", str(kpis)],
    )
    export_results.main()
    with out.open(newline="", encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == 12
    assert json.loads(kpis.read_text(encoding="utf-8")) == export_results.summarize(rows)
    assert "Wrote 12 rows" in capsys.readouterr().out



def test_module_runs_as_a_script(tmp_path, monkeypatch, capsys):
    db_path, _ = seeded_rows(tmp_path, devices=1, tests_per_device=2)
    out, kpis = tmp_path / "out.csv", tmp_path / "kpis.json"
    monkeypatch.setattr(
        sys, "argv", ["export_results", "--db", db_path, "--out", str(out), "--kpis", str(kpis)]
    )
    monkeypatch.delitem(sys.modules, "bi.export_results")  # run it fresh, as python -m does
    runpy.run_module("bi.export_results", run_name="__main__")
    assert "Wrote 2 rows" in capsys.readouterr().out

# --- The committed dataset the dashboard guides are written against ---------


def test_committed_csv_is_the_seeded_dataset(tmp_path):
    _, rows = seeded_rows(tmp_path)
    out = tmp_path / "regenerated.csv"
    export_results.write_csv(rows, out)
    committed = (BI_DATA / "test_results.csv").read_text(encoding="utf-8")
    assert out.read_text(encoding="utf-8") == committed


def test_committed_kpi_summary_matches_the_committed_csv(tmp_path):
    _, rows = seeded_rows(tmp_path)
    committed = json.loads((BI_DATA / "kpi_summary.json").read_text(encoding="utf-8"))
    assert export_results.summarize(rows) == committed


@pytest.mark.parametrize(
    ("kpi", "value"),
    [
        ("total_tests", 500),
        ("passed_tests", 447),
        ("failure_count", 53),
        ("pass_rate", 89.4),
        ("devices_tested", 20),
        ("devices_with_failures", 17),
        ("worst_devices", ["FPGA-015"]),
        ("worst_device_pass_rate", 72.0),
    ],
)
def test_kpi_values_quoted_in_the_dashboard_guides(kpi, value):
    committed = json.loads((BI_DATA / "kpi_summary.json").read_text(encoding="utf-8"))
    assert committed[kpi] == value
