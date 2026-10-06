# Tableau Public Build Guide

How to build the hardware test dashboard in Tableau Public from the exported CSV.

The workbook is not in the repository; it has to be built by hand by following the steps below. The calculated fields have not been run in Tableau yet, so step 6 lists the value each one should show. If a sheet disagrees with that table, a calculation or a field type is wrong.

Tableau Public saves workbooks to the public web. The dataset here is simulated, so that is fine.

---

## 1. Get the Data

The dataset is already in the repository at `bi/data/test_results.csv`: 500 simulated tests across 20 devices, one row per test.

To rebuild it from scratch:

```bash
python -m scripts.generate_test_data --seed 42 --now 2026-10-01T00:00:00 --db bi_seed.db --reset
python -m bi.export_results --db bi_seed.db
```

To load and export through Oracle instead, replace `--db bi_seed.db` with `--backend oracle` in both commands. Both backends produce the same file, byte for byte.

---

## 2. Connect the CSV

1. Open Tableau Public and choose **Connect > To a File > Text file**.
2. Pick `bi/data/test_results.csv`.
3. On the Data Source page, check the field types by clicking the icon above each column:

| Field | Type |
| --- | --- |
| `result_id` | Number (whole) |
| `device_id`, `test_type`, `result`, `failure_reason` | String |
| `passed`, `failed` | Number (whole) |
| `voltage_v`, `current_a`, `temperature_c`, `duration_s` | Number (decimal) |
| `voltage_fault`, `current_fault`, `temperature_fault`, `duration_fault` | Number (whole) |
| `tested_at` | Date & Time |
| `test_date` | Date |

4. Go to **Sheet 1**. In the Data pane, drag `result_id` up into the dimensions if Tableau placed it with the measures.

---

## 3. Create the Calculated Fields

For each one, choose **Analysis > Create Calculated Field**, type the name, and paste the formula.

**Failed Flag**

```text
IF [result] = "FAIL" THEN 1 ELSE 0 END
```

**Failure Count**

```text
SUM([Failed Flag])
```

**Pass Rate**

```text
SUM(IF [result] = "PASS" THEN 1 ELSE 0 END) / COUNT([result_id])
```

Right-click `Pass Rate`, choose **Default Properties > Number Format > Percentage**, and set 1 decimal place.

**Devices With Failures**

```text
COUNTD(IF [result] = "FAIL" THEN [device_id] END)
```

**Total Tests**

```text
COUNT([result_id])
```

`Failed Flag` gives the same value as the `failed` column in the CSV. It is built here so the pass and fail logic is visible in the workbook.

---

## 4. Build the Sheets

**KPI: Tests.** Drag `Total Tests` to **Text**. Name the sheet `KPI Tests`.

**KPI: Pass rate.** Drag `Pass Rate` to **Text**. Name the sheet `KPI Pass Rate`.

**KPI: Failures.** Drag `Failure Count` to **Text**. Name the sheet `KPI Failures`.

**KPI: Devices with failures.** Drag `Devices With Failures` to **Text**. Name the sheet `KPI Devices With Failures`.

**KPI: Worst device.**

1. Drag `device_id` to **Rows** and `Pass Rate` to **Text**.
2. Drag `device_id` to **Filters**, open the **Top** tab, choose **By field**, and set it to **Bottom 1 by Pass Rate**.
3. Name the sheet `KPI Worst Device`.

**Pass rate by device.**

1. Drag `device_id` to **Rows** and `Pass Rate` to **Columns**.
2. Sort ascending by `Pass Rate`, so the worst device is at the top.
3. Drag `Pass Rate` to **Color**.
4. In the Analytics pane, drag **Average Line** onto the chart for a reference.

**Failures per day.**

1. Right-drag `test_date` to **Columns** and choose the continuous **Day** option (the green `test_date (Day)` entry showing a full date).
2. Drag `Failure Count` to **Rows**.
3. Set the mark type to **Bar**.

**Faults by kind.**

1. Drag **Measure Names** to **Rows** and **Measure Values** to **Columns**.
2. In the Measure Values card, remove everything except `SUM(voltage_fault)`, `SUM(current_fault)`, and `SUM(temperature_fault)`.
3. Sort descending.

**Pass rate by test type.** Drag `test_type` to **Columns** and `Pass Rate` to **Rows**.

**Failed tests.**

1. Drag `tested_at` (exact date), `device_id`, `test_type`, and `failure_reason` to **Rows**.
2. Drag `result` to **Filters** and keep only `FAIL`.

---

## 5. Assemble and Publish

1. Choose **Dashboard > New Dashboard** and set the size to **Automatic** or 1366 x 768.
2. Place the five KPI sheets in a row along the top.
3. Put `Pass rate by device` and `Failures per day` in the middle row.
4. Put `Faults by kind`, `Pass rate by test type`, and `Failed tests` in the bottom row.
5. Click `Pass rate by device`, then the funnel icon (**Use as Filter**), so clicking a device filters the rest of the dashboard.
6. Add a title: `Hardware Test Analytics`.
7. Choose **File > Save to Tableau Public As**, sign in, and name the workbook.
8. Copy the public link, take a screenshot, and save it as `screenshots/tableau_dashboard.png`.
9. In the main `README.md`, replace the Tableau placeholders in the **Dashboards** section with the link and the screenshot.

---

## 6. Check the Numbers

With no filter applied, the KPI sheets must show:

| Sheet or field | Expected value |
| --- | --- |
| `Total Tests` | 500 |
| `Failure Count` | 53 |
| `Pass Rate` | 89.4% |
| `Devices With Failures` | 17 |
| Worst device | FPGA-015 at 72.0% |
| `SUM(voltage_fault)` | 13 |
| `SUM(current_fault)` | 24 |
| `SUM(temperature_fault)` | 17 |

`SUM([Failed Flag])` and `SUM([failed])` must both be 53. The three fault counts add up to 54, one more than the 53 failures, because test 235 on `FPGA-010` failed on both voltage and current.

**Pass rate by device**

Sorted ascending, the chart starts with:

| Device | Failures | Pass rate |
| --- | --- | --- |
| FPGA-015 | 7 | 72.0% |
| FPGA-011 | 5 | 80.0% |
| FPGA-001, FPGA-002, FPGA-007, FPGA-010, FPGA-020 | 4 each | 84.0% |
| FPGA-004, FPGA-013, FPGA-019 | 3 each | 88.0% |
| FPGA-003, FPGA-006, FPGA-012, FPGA-016, FPGA-017 | 2 each | 92.0% |
| FPGA-005, FPGA-008 | 1 each | 96.0% |
| FPGA-009, FPGA-014, FPGA-018 | 0 | 100.0% |

Every device has 25 tests.

**Pass rate by test type**

| Test type | Tests | Failures | Pass rate |
| --- | --- | --- | --- |
| FUNCTIONAL | 112 | 11 | 90.2% |
| MEMORY | 108 | 14 | 87.0% |
| POWER | 89 | 12 | 86.5% |
| THERMAL | 99 | 10 | 89.9% |
| UART | 92 | 6 | 93.5% |

**Failures per day**

- Tests run from 2026-09-01 to 2026-09-30, on all 30 days.
- 24 of those days have at least one failure.
- The tallest bars are 4 failures, on 2026-09-13 and 2026-09-24.

**Filter check**

Click `FPGA-015` in the device chart. The KPIs should change to 25 tests, 7 failures, and a 72.0% pass rate.

All of these values come from `bi/data/kpi_summary.json`, which `bi/export_results.py` writes next to the CSV, and from the CSV itself.
