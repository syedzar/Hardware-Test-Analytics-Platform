# Power BI Build Guide

How to build the hardware test dashboard in Power BI Desktop from the exported CSV.

The `.pbix` file is not in the repository; it has to be built by hand by following the steps below. The measures in `measures.dax` have not been run in Power BI yet, so step 6 lists the value each one should show. If a card disagrees with that table, the measure or a column type is wrong.

---

## 1. Get the Data

The dataset is already in the repository at `bi/data/test_results.csv`: 500 simulated tests across 20 devices, one row per test.

To rebuild it from scratch:

```bash
python -m scripts.generate_test_data --seed 42 --now 2026-10-01T00:00:00 --db bi_seed.db --reset
python -m bi.export_results --db bi_seed.db
```

`--db bi_seed.db` keeps this dataset in its own SQLite file, so the everyday `test_data.db` is left alone.

To load and export through Oracle instead, replace `--db bi_seed.db` with `--backend oracle` in both commands. Both backends produce the same file, byte for byte.

---

## 2. Load the CSV

1. Open Power BI Desktop and choose **Get data > Text/CSV**.
2. Pick `bi/data/test_results.csv` and click **Transform Data**.
3. In Power Query, rename the query to `test_results`. The measures use this name.
4. Check the column types:

| Column | Type |
| --- | --- |
| `result_id` | Whole Number |
| `device_id`, `test_type`, `result`, `failure_reason` | Text |
| `passed`, `failed` | Whole Number |
| `voltage_v`, `current_a`, `temperature_c`, `duration_s` | Decimal Number |
| `voltage_fault`, `current_fault`, `temperature_fault`, `duration_fault` | Whole Number |
| `tested_at` | Date/Time |
| `test_date` | Date |

5. Click **Close & Apply**.

`failure_reason` is empty for passing tests. Leave those as blank.

---

## 3. Add the Measures

Open `measures.dax`. For each block, choose **Modeling > New measure**, paste the block, and press Enter.

Then set the format of `Pass Rate` and `Worst Device Pass Rate` to **Percentage** with **1** decimal place, and the three averages to **2** decimal places.

| Measure | Meaning |
| --- | --- |
| `Total Tests` | Number of test results |
| `Passed Tests` | Tests that passed |
| `Failure Count` | Tests that failed |
| `Pass Rate` | Passed tests divided by all tests |
| `Devices Tested` | Distinct devices |
| `Devices With Failures` | Distinct devices with at least one failed test |
| `Worst Device Pass Rate` | Lowest pass rate of any device |
| `Worst Device` | The device with that pass rate (ties are all listed) |
| `Voltage Faults`, `Current Faults`, `Temperature Faults` | Failed checks of each kind |
| `Average Voltage (V)`, `Average Current (A)`, `Average Temperature (C)` | Mean measurements |

---

## 4. Build the Visuals

One page, 16:9.

**Top row: five cards**

| Card | Field |
| --- | --- |
| Tests | `Total Tests` |
| Pass rate | `Pass Rate` |
| Failures | `Failure Count` |
| Devices with failures | `Devices With Failures` |
| Worst device | `Worst Device` |

**Middle row**

1. **Pass rate by device** (clustered bar chart). Y-axis `device_id`, X-axis `Pass Rate`. Sort by `Pass Rate` ascending so the worst device is at the top. Add a constant line at the overall pass rate from the card.
2. **Failures per day** (clustered column chart). X-axis `test_date`, Y-axis `Failure Count`. Set the X-axis type to **Continuous**.

**Bottom row**

3. **Faults by kind** (clustered bar chart). Put `Voltage Faults`, `Current Faults`, and `Temperature Faults` on the X-axis with nothing on the Y-axis.
4. **Pass rate by test type** (clustered column chart). X-axis `test_type`, Y-axis `Pass Rate`.
5. **Failed tests** (table). Columns `tested_at`, `device_id`, `test_type`, `voltage_v`, `current_a`, `temperature_c`, `failure_reason`. Add a visual-level filter `failed` is `1`, and sort by `tested_at` descending.

**Slicers**

Add slicers for `device_id` and `test_type`, and a between slicer for `test_date`.

---

## 5. Save and Capture

1. Save the report as `bi/power_bi/hardware_test_analytics.pbix`.
2. Clear every slicer, take a screenshot of the page, and save it as `screenshots/powerbi_dashboard.png`.
3. In the main `README.md`, replace the Power BI placeholder in the **Dashboards** section with the screenshot.

---

## 6. Check the Numbers

With no slicer selected, the cards must show:

| Measure | Expected value |
| --- | --- |
| `Total Tests` | 500 |
| `Passed Tests` | 447 |
| `Failure Count` | 53 |
| `Pass Rate` | 89.4% |
| `Devices Tested` | 20 |
| `Devices With Failures` | 17 |
| `Worst Device` | FPGA-015 |
| `Worst Device Pass Rate` | 72.0% |
| `Voltage Faults` | 13 |
| `Current Faults` | 24 |
| `Temperature Faults` | 17 |
| `Average Voltage (V)` | 3.30 |
| `Average Current (A)` | 0.54 |
| `Average Temperature (C)` | 53.04 |

The three fault counts add up to 54, one more than the 53 failures, because test 235 on `FPGA-010` failed on both voltage and current.

**Pass rate by device**

| Device | Tests | Failures | Pass rate |
| --- | --- | --- | --- |
| FPGA-001 | 25 | 4 | 84.0% |
| FPGA-002 | 25 | 4 | 84.0% |
| FPGA-003 | 25 | 2 | 92.0% |
| FPGA-004 | 25 | 3 | 88.0% |
| FPGA-005 | 25 | 1 | 96.0% |
| FPGA-006 | 25 | 2 | 92.0% |
| FPGA-007 | 25 | 4 | 84.0% |
| FPGA-008 | 25 | 1 | 96.0% |
| FPGA-009 | 25 | 0 | 100.0% |
| FPGA-010 | 25 | 4 | 84.0% |
| FPGA-011 | 25 | 5 | 80.0% |
| FPGA-012 | 25 | 2 | 92.0% |
| FPGA-013 | 25 | 3 | 88.0% |
| FPGA-014 | 25 | 0 | 100.0% |
| FPGA-015 | 25 | 7 | 72.0% |
| FPGA-016 | 25 | 2 | 92.0% |
| FPGA-017 | 25 | 2 | 92.0% |
| FPGA-018 | 25 | 0 | 100.0% |
| FPGA-019 | 25 | 3 | 88.0% |
| FPGA-020 | 25 | 4 | 84.0% |

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
- The most failures on one day is 4, on 2026-09-13 and again on 2026-09-24.

**Slicer check**

Select `FPGA-015` in the device slicer. The cards should change to 25 tests, 7 failures, and a 72.0% pass rate, with 1 voltage fault, 4 current faults, and 2 temperature faults.

All of these values come from `bi/data/kpi_summary.json`, which `bi/export_results.py` writes next to the CSV, and from the CSV itself. `tests/test_export.py` fails if the committed files and the headline numbers above stop matching the generated data.
