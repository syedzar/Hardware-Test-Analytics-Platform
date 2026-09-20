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
             services.py                         database.py
        evaluate_test, statistics             SQL against SQLite
        (pure functions, no I/O)              (parameterized queries)
                                                       |
                                                       v
                                                 test_data.db
```

### Modules

- **`main.py`** handles routes, status codes, and error mapping. It receives requests and coordinates the other modules but contains no engineering rules and no SQL.
- **`schemas.py`** describes the shape and basic validity of request and response data using Pydantic.
- **`services.py`** contains the engineering rules, the pass rate calculation, and the shaping of statistics. It depends only on `config.py`.
- **`database.py`** contains every SQL statement and the connection handling. It depends only on `config.py`.
- **`config.py`** holds the engineering limits and the database path.

`services.py` imports neither FastAPI nor sqlite3, so `evaluate_test()` can be unit-tested with plain function calls and no web server.

`database.py` accepts an optional `db_path` argument, so tests can use a temporary database instead of the real one.

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

### Connection per operation

Each database function opens and closes its own connection. This is simple and safe with SQLite and FastAPI's threadpool. A connection pool would be the next step under real load.

---

## Testing Strategy

Testing happens at several levels.

- **`test_evaluation.py`** is unit testing. It covers every rule, boundary values, and multiple simultaneous failures.
- **`test_database.py`** is integration testing against a temporary SQLite database. It covers inserting, retrieving, filtering, deleting, aggregates, and injection safety.
- **`test_api.py`** tests the API through FastAPI's test client. It covers status codes, input validation, statistics, and persistence across restarts.
- **`test_generator.py`** tests the data generator. It checks the row count, that both PASS and FAIL results appear, and that output is reproducible with a seed.

GitHub Actions runs the whole suite on every push and pull request.

---

## Future Work

- Reading real measurements from a microcontroller over UART/USB serial, using a small reader that parses lines such as `DEVICE=ARDUINO-001,VOLTAGE=3.31,CURRENT=0.42,TEMP=44.3` and posts them to `POST /tests`
- Replacing SQLite with PostgreSQL
- Per-device limits
- Authentication
- Pagination and search
- CSV export
- A web dashboard
- Failure trend detection
