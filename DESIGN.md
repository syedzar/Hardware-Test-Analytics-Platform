# Design

## Goal

Receive engineering test data, validate it, evaluate it, store it, retrieve
it, analyze it, and automatically verify that the software doing so keeps
working.

## Architecture

```text
                 HTTP / JSON
   Client ─────────────────────> main.py (FastAPI routes)
                                     │
                    ┌────────────────┼─────────────────┐
                    ▼                                  ▼
             services.py                         database.py
        evaluate_test, statistics             SQL against SQLite
        (pure functions, no I/O)              (parameterized queries)
                                                       │
                                                       ▼
                                                 test_data.db
```

| Module | Responsibility | Depends on |
|---|---|---|
| `main.py` | Routes, status codes, error mapping | schemas, services, database |
| `schemas.py` | Shape and basic validity of request/response data | pydantic |
| `services.py` | Engineering rules, pass rate, statistics shaping | config |
| `database.py` | Every SQL statement; connection handling | config |
| `config.py` | Limits, DB path | — |

`services.py` imports neither FastAPI nor sqlite3, so `evaluate_test()` can be
unit-tested with plain function calls. `database.py` accepts a `db_path`
argument so tests use a temporary database.

## Two kinds of validation

1. **Input validation** (`schemas.py`, Pydantic → HTTP 422): is the request
   well formed? Wrong types, empty `device_id`, unknown `test_type`, missing
   fields, NaN/infinity, negative duration.
2. **Engineering validation** (`services.evaluate_test`, → PASS/FAIL): is a
   well-formed measurement within limits? `temperature = 95` is a valid
   request; it is stored as a FAIL.

## PASS/FAIL evaluation

Each measurement has its own check function returning a failure message or
`None`. `evaluate_test` runs all checks and collects every message, so a test
with three out-of-range values records three reasons (joined with `; `).
Limits are inclusive: 3.6 V and 80.0 °C pass; 3.61 V and 80.1 °C fail. The
result is never taken from the client.

## Data flow for `POST /tests`

1. FastAPI parses the JSON into `TestCreate` (422 if invalid).
2. `evaluate_test()` returns `PASS`/`FAIL` plus failure reasons.
3. `database.insert_test()` runs a parameterized `INSERT`, adds a UTC
   timestamp, and reads the row back.
4. The route returns the stored record with status 201.

## Database

One table, `test_results` (schema in `database.py`), plus an index on
`device_id` for per-device queries. SQLite generates the integer primary key.
Statistics use SQL aggregates (`COUNT`, `SUM(CASE …)`, `AVG`) in a single
query; only pass-rate percentage and rounding happen in Python.

All queries use `?` placeholders. A test confirms that a device id such as
`x' OR '1'='1` is treated as data.

## Decisions worth knowing

- **Duration 0 vs. negative.** Negative durations are rejected as invalid
  input (422). A duration of exactly 0 is valid input but fails the
  engineering rule "duration must be greater than 0", so that rule is
  reachable and tested through the API.
- **Unknown devices.** `GET /devices/{id}/tests` returns `200 []` (a filter
  with no matches). `GET /devices/{id}/statistics` returns `404`, because
  there is nothing to compute statistics over.
- **Timestamps** are stored as UTC ISO 8601 text (`2026-09-20T14:32:08`),
  which sorts correctly as a string.
- **Validation error bodies** omit the rejected input. FastAPI's default
  echoes it back, which crashed on `NaN` (not representable in JSON) and
  returned a 500; a small exception handler in `main.py` fixes this and has a
  regression test.
- **Simulated data** uses per-device bias and injected faults rather than
  uniform random ranges. Uniform ranges over the values in the original spec
  give only ~40 % passing tests; this generator gives ~88 %, closer to a real
  production line, and different devices have different failure profiles.
- **Connection per operation.** Simple and safe with SQLite and FastAPI's
  threadpool; a connection pool would be the next step under real load.

## Testing strategy

| File | Level | What it proves |
|---|---|---|
| `test_evaluation.py` | Unit | Every rule, boundaries, multiple simultaneous failures |
| `test_database.py` | Integration (SQLite) | CRUD, filtering, aggregates, injection safety |
| `test_api.py` | API (TestClient) | Status codes, validation, statistics, persistence |
| `test_generator.py` | Script | Row counts, both outcomes present, reproducible with a seed |

GitHub Actions runs the whole suite on every push and pull request.

## Future work

Real hardware ingestion over serial (a small reader that parses lines such as
`DEVICE=ARDUINO-001,VOLTAGE=3.31,CURRENT=0.42,TEMP=44.3` and posts them to
`POST /tests`), PostgreSQL, per-device limits, authentication, pagination,
CSV export, dashboard, trend detection.
