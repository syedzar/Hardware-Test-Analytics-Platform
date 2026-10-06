# Hardware Test Analytics Platform: Design

This document explains how the Hardware Test Analytics Platform is structured and why it was built this way.

The core design goal is:

> Receive hardware test data, validate it, evaluate it, store it, retrieve it, analyze it, and automatically verify that the software doing so keeps working.

---

## Architecture

The application is split into layers. Each layer has one job and only talks to the layer below it.

```text
                 HTTP / JSON
   Client ─────────────────────> main.py (FastAPI routes)
                                     |
                    +----------------+-----------------+
                    |                                  |
                    v                                  v
             services.py                        repository.py
        evaluate_test, statistics           picks the backend from
        (pure functions, no I/O)                 DB_BACKEND
                                                       |
                                        +--------------+--------------+
                                        |                             |
                                        v                             v
                                   database.py                  oracle_db.py
                                SQL against SQLite        PL/SQL package and views
                                        |                             |
                                        v                             v
                                   test_data.db             Oracle Database Free
```

### Modules

- **`main.py`** handles routes, status codes, and error mapping. It receives requests and coordinates the other modules but contains no engineering rules and no SQL.
- **`schemas.py`** describes the shape and basic validity of request and response data using Pydantic.
- **`services.py`** contains the engineering rules, the pass rate calculation, and the shaping of statistics. It depends only on `config.py`.
- **`repository.py`** returns the data-access module named by `DB_BACKEND`. It is the only place that knows there are two.
- **`database.py`** is the SQLite backend. It contains every SQLite statement and the connection handling. It depends only on `config.py`.
- **`oracle_db.py`** is the Oracle backend. It exposes the same functions as `database.py`, calls the PL/SQL package for writes and statistics, and reads through two views.
- **`config.py`** holds the engineering limits, the backend choice, and the connection settings.

`services.py` imports neither FastAPI nor sqlite3, so `evaluate_test()` can be unit-tested with plain function calls and no web server.

`database.py` accepts an optional `db_path` argument, so tests can use a temporary database instead of the real one.

`main.py` asks `repository.get_backend()` for the backend on every request rather than importing one, so neither `main.py` nor `services.py` changed behaviour when Oracle was added.

---

## Two Kinds of Validation

The project deliberately separates two different questions.

### Input Validation

Handled in `schemas.py` by Pydantic. It asks whether the request is well formed.

Requests rejected with HTTP 422 include:

- Wrong types, such as `"voltage": "hello"`
- An empty or whitespace-only `device_id`
- An unknown `test_type`
- Missing fields
- NaN or infinity values
- A negative duration

### Engineering Validation

Handled in `services.evaluate_test`. It asks whether a well-formed measurement is within limits.

`temperature = 95` is a perfectly valid request. It is accepted, evaluated, and stored as a FAIL.

---

## PASS/FAIL Evaluation

Each measurement has its own check function that returns either a failure message or `None`.

`evaluate_test` runs every check and collects all the messages. A test with three out-of-range values therefore records three failure reasons, joined with `; `.

Key behaviours:

- Limits are inclusive, so 3.6 V and 80.0 °C pass while 3.61 V and 80.1 °C fail
- The result is never taken from the client
- The result object is immutable, so a decision cannot be changed after it is made

---

## Data Flow for POST /tests

```text
Client
  |
  | JSON body
  v
FastAPI parses it into TestCreate  ---- invalid ----> 422
  |
  v
evaluate_test()
  |
  | PASS / FAIL + failure reasons
  v
database.insert_test()
  |
  | parameterized INSERT, UTC timestamp, read row back
  v
SQLite
  |
  v
Stored record returned with status 201
```

---

## Database

The database has one table, `test_results`, plus an index on `device_id` so per-device queries do not need to scan every row. SQLite generates the integer primary key.

Statistics use SQL aggregates in a single query:

- `COUNT(*)` for the total number of tests
- `SUM(CASE WHEN ...)` for the number of passes and failures
- `AVG()` for voltage, current, and temperature
- `WHERE device_id = ?` to restrict the same query to one device

Only the pass rate percentage and the rounding are done in Python.

All queries use `?` placeholders, so user input is always treated as data and never as SQL. A test confirms that a device ID such as `x' OR '1'='1` matches nothing.

---

## Two Backends

Oracle was added as a second backend next to SQLite, not as a replacement. SQLite still needs no setup, and the original 68 tests run unchanged.

### One interface, two modules

Both modules expose the same functions and return records in the same shape: the same keys, floats for measurements, and ISO 8601 text for timestamps. `repository.get_backend()` returns one or the other. The Oracle module is imported only when it is asked for.

A class hierarchy was not needed. The backend is a module, and the interface is checked by a test that asserts both modules have every function.

### A normalized schema on Oracle

SQLite keeps one table. On Oracle the same data is split into three:

- `devices` holds each device once, with a surrogate key
- `test_types` is a lookup of the five supported test types
- `test_results` points at both with foreign keys

Check constraints repeat the rules that matter most: the result is `PASS` or `FAIL`, a failure has a reason, the duration is not negative, and no measurement is NaN or infinite. They hold even if a row is written without going through the package, and tests confirm that.

### Why writes go through PL/SQL

`record_test_result` validates the values, looks up the test type, registers the device if it is new, and inserts the row, all in one round trip. Invalid values raise `ORA-20001` to `ORA-20004`, which the Python layer turns into a `ValueError`.

The procedure does not commit. The Python layer commits on success and rolls back on any error, so a failed insert cannot leave a newly registered device behind.

### Statistics through ref cursors

`get_statistics` opens two ref cursors, one row of overall figures and one row per device. `get_device_statistics` opens one for a single device. The aggregates are the same `COUNT`, `SUM`, and `AVG` as in SQLite, so the pass rate and rounding stay in `services.py` for both backends.

### Keeping the two in agreement

Measurements are stored as `BINARY_DOUBLE`, the same IEEE 754 double that SQLite uses for `REAL`, so a stored value reads back identically from both.

`test_backend_parity.py` loads the same 500 seeded results into both databases and compares every record, every statistic, seven API responses, and the exported CSV. Averages are sums of doubles added in a different order, so the raw values are compared to 12 significant figures and the reported, rounded values are compared exactly.

### Schema as SQL files

The Oracle objects live in `db/oracle` as `.sql` files, each statement ending in a `/` line. `oracle_db.py` splits on those lines and runs them at startup; the same files run unchanged in SQL*Plus. Every script is safe to repeat.

Oracle creates a package that fails to compile without raising an error, so `init_db` checks `user_errors` afterwards and stops with the compiler messages if there are any.

### Credentials

Nothing is hardcoded. The Oracle user, password, and connection string come from environment variables, optionally loaded from a local `.env` file that git ignores. `.env.example` lists the names.

---

## Reporting and BI Export

Both backends have a view, `v_test_report`, with one flat row per test. It adds 1/0 `passed` and `failed` flags and one flag per kind of fault. The fault flags are read from the stored failure reason, so the engineering limits stay in `config.py` and are not repeated in SQL.

`bi/export_results.py` writes that view to a CSV for Power BI and Tableau, along with a small JSON file of KPI values. The dashboard build guides quote those values, and a test fails if the committed files stop matching the generated data.

---

## Decisions Worth Knowing

### Duration of 0 versus negative

Negative durations are rejected as invalid input with a 422. A duration of exactly 0 is valid input but fails the engineering rule that duration must be greater than 0. This keeps that rule reachable and testable through the API.

### Unknown devices

`GET /devices/{id}/tests` returns `200` with an empty list, because it is a filter that matched nothing.

`GET /devices/{id}/statistics` returns `404`, because there is nothing to calculate statistics over.

### Timestamps

Timestamps are stored as UTC ISO 8601 text, such as `2026-09-20T14:32:08`. This format sorts correctly as a plain string.

### Validation error responses

FastAPI normally echoes rejected input back inside the 422 response. For a NaN value this crashed, because NaN cannot be represented in JSON, and the client received a 500 instead of a 422.

A small exception handler in `main.py` now returns only the location, message, and type of each error. A regression test covers this.

### Simulated data

Uniform random values over the ranges in the original specification give only about 40 percent passing tests. The generator instead uses per-device bias and occasional injected faults, which gives about 88 percent and makes different devices have different failure profiles.

The generator builds its rows before touching a database, so the same seed gives the same rows on either backend.

### Connection per operation

Each SQLite function opens and closes its own connection. This is simple and safe with SQLite and FastAPI's threadpool.

Connecting to Oracle is slower, so the Oracle backend borrows connections from a small pool instead.

---

## Testing Strategy

Testing happens at several levels.

- **`test_evaluation.py`** is unit testing. It covers every rule, boundary values, and multiple simultaneous failures.
- **`test_database.py`** is integration testing against a temporary SQLite database. It covers inserting, retrieving, filtering, deleting, aggregates, and injection safety.
- **`test_api.py`** tests the API through FastAPI's test client. It covers status codes, input validation, statistics, and persistence across restarts.
- **`test_generator.py`** tests the data generator. It checks the row count, that both PASS and FAIL results appear, and that output is reproducible with a seed.
- **`test_generator_cli.py`**, **`test_reporting.py`**, **`test_repository.py`**, **`test_export.py`**, and **`test_oracle_sql.py`** cover the generator's command line, the reporting view, the backend selector, the CSV export, and the SQL file splitter. None of them need a database server.
- **`test_oracle.py`** is integration testing against a real Oracle database. It covers the schema, each validation error of the PL/SQL procedure, the constraints, the ref cursor statistics, and the API served from Oracle.
- **`test_backend_parity.py`** proves the two backends agree on the same seeded data.

The last two are skipped, with the reason shown, when Oracle is not running.

GitHub Actions runs the whole suite on every push and pull request, without Oracle on three Python versions and once against an Oracle service container.

---

## Future Work

- Reading real measurements from a microcontroller over UART/USB serial, using a small reader that parses lines such as `DEVICE=ARDUINO-001,VOLTAGE=3.31,CURRENT=0.42,TEMP=44.3` and posts them to `POST /tests`
- Building the Power BI and Tableau dashboards from the prepared export
- Per-device limits
- Authentication
- Pagination and search
- A web dashboard
- Failure trend detection
