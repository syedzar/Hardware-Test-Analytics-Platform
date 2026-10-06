# Oracle Schema and PL/SQL

Everything the Oracle backend needs, written for Oracle Database Free. It was developed and tested on the `gvenzl/oracle-free:23-slim-faststart` container, which reports itself as Oracle AI Database 26ai Free, version 23.26.3. The scripts use `IF NOT EXISTS`, so they need release 23 or later.

`app/oracle_db.py` runs these files in order when the API starts. Every statement ends with a `/` line, so the same files also run unchanged in SQL*Plus.

| File | Contents |
| --- | --- |
| `schema.sql` | Tables, constraints, indexes, and the test type lookup rows |
| `views.sql` | The reporting view and the failures view |
| `test_stats_pkg.sql` | The PL/SQL package specification and body |
| `drop.sql` | Removes all of the above (used by `--reset`) |

All four are safe to run more than once.

---

## Tables

| Table | Purpose | Keys and constraints |
| --- | --- | --- |
| `devices` | One row per device under test | Identity primary key, unique `device_code` |
| `test_types` | Lookup of the five supported test types | Identity primary key, unique `type_code` |
| `test_results` | One row per test | Identity primary key, foreign keys to `devices` and `test_types`, and four check constraints |

The check constraints on `test_results`:

| Constraint | Rule |
| --- | --- |
| `ck_results_result` | `result` is `PASS` or `FAIL` |
| `ck_results_reason` | A `FAIL` has a failure reason and a `PASS` does not |
| `ck_results_duration` | `duration_s` is not negative |
| `ck_results_finite` | No measurement is NaN or infinite |

Indexes:

| Index | Columns | Why |
| --- | --- | --- |
| `ix_results_device_result` | `device_id, result` | Covers the device foreign key and per-device pass and fail counts |
| `ix_results_test_type` | `test_type_id` | Covers the test type foreign key |
| `ix_results_tested_at` | `tested_at` | Date-range filters in reports |

Measurements are stored as `BINARY_DOUBLE`, so a value written through the API reads back exactly as it does from SQLite.

---

## Views

| View | Rows | Used by |
| --- | --- | --- |
| `v_test_report` | Every test, flattened: device code and test type joined in, 1/0 `passed` and `failed` flags, one 1/0 flag per kind of fault, and a `test_date` column | Every read in `app/oracle_db.py`, the statistics routines, and `bi/export_results.py` |
| `v_failed_tests` | The same columns, failed tests only | `GET /failures` |

Both views are read-only.

---

## Package `test_stats_pkg`

| Routine | Kind | What it does | Called from |
| --- | --- | --- | --- |
| `record_test_result` | Procedure | Validates the values, registers the device if it is new, inserts the test, and returns the new id through an `OUT` parameter | `oracle_db.insert_test` (`POST /tests` and the data generator) |
| `device_pass_rate` | Function | Returns one device's pass rate as a percentage rounded to one decimal place, or `NULL` if the device has no tests | `oracle_db.get_device_pass_rate` |
| `get_statistics` | Procedure | Opens two ref cursors: one row of overall totals and averages, and the same figures per device with the pass rate | `oracle_db.get_statistics` (`GET /statistics`) and `oracle_db.get_statistics_by_device` |
| `get_device_statistics` | Procedure | Opens a ref cursor with the totals and averages for one device | `oracle_db.get_device_statistics` (`GET /devices/{id}/statistics`) |

None of the routines commit. The caller owns the transaction, so a failed call leaves nothing behind.

### Errors raised by `record_test_result`

| Code | Raised when |
| --- | --- |
| `ORA-20001` | The device code is empty or longer than 64 characters |
| `ORA-20002` | The test type is not in `test_types` |
| `ORA-20003` | The result is not `PASS` or `FAIL`, a `FAIL` has no reason, or a `PASS` has one |
| `ORA-20004` | A measurement is null, NaN, or infinite, or the duration is negative |

`oracle_db.insert_test` turns these into a Python `ValueError`. Any other database error is passed through unchanged.

The procedure also handles two built-in exceptions: `NO_DATA_FOUND` when a device or test type is looked up, and `DUP_VAL_ON_INDEX` when two sessions register the same new device at the same moment.

---

## Running the Files by Hand

With the container from `docker-compose.yml` running, open SQL*Plus as the application user (it asks for `ORACLE_PASSWORD`):

```bash
docker compose exec oracle sqlplus htap@//localhost/FREEPDB1
```

A routine can then be called directly:

```sql
SELECT test_stats_pkg.device_pass_rate('FPGA-015') AS pass_rate FROM dual;
```

On the seeded dataset (`--seed 42`) this returns `72`.

To run a whole file, start it from the SQL prompt with `@`, or pipe it in from the host.
