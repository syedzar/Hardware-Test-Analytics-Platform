# Engineering Test Data Platform

A backend service that simulates how an engineering team collects, validates,
stores and analyzes hardware test results. Tests for devices such as
`FPGA-001` are submitted over a REST API; the server decides PASS/FAIL from
engineering limits, stores the result in SQLite, and exposes queries and
statistics.

**Stack:** Python, FastAPI, SQLite (plain SQL), Pytest, GitHub Actions, Docker.

```text
User ── HTTP/JSON ──> FastAPI ──> Python logic ──SQL──> SQLite
                                   (services.py)     (database.py)
```

See [DESIGN.md](DESIGN.md) for architecture and design decisions.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows   (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

python -m scripts.generate_test_data      # optional: 500 simulated tests
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/docs> for the interactive Swagger UI. The database
file (`test_data.db`) is created automatically.

## Example

```bash
curl -X POST http://127.0.0.1:8000/tests \
  -H "Content-Type: application/json" \
  -d '{"device_id":"FPGA-010","test_type":"THERMAL","voltage":3.29,
       "current":0.44,"temperature":88.3,"duration":3.2}'
```

```json
{
  "id": 501,
  "device_id": "FPGA-010",
  "test_type": "THERMAL",
  "voltage": 3.29,
  "current": 0.44,
  "temperature": 88.3,
  "duration": 3.2,
  "result": "FAIL",
  "failure_reason": "Temperature above maximum limit (88.3 C > 80.0 C)",
  "timestamp": "2026-09-20T13:01:07"
}
```

`result` is never accepted from the client; it is always computed.

## Endpoints

| Method | Path | Description | Success | Errors |
|---|---|---|---|---|
| POST | `/tests` | Submit a test; evaluated and stored | 201 | 422 invalid input |
| GET | `/tests` | All tests | 200 | |
| GET | `/tests/{id}` | One test | 200 | 404 |
| DELETE | `/tests/{id}` | Delete a test | 204 | 404 |
| GET | `/devices/{device_id}/tests` | All tests for a device (empty list if none) | 200 | |
| GET | `/failures` | Failed tests only | 200 | |
| GET | `/statistics` | Overall counts, pass rate, averages | 200 | |
| GET | `/devices/{device_id}/statistics` | Same, for one device | 200 | 404 unknown device |

Test types: `POWER`, `UART`, `MEMORY`, `THERMAL`, `FUNCTIONAL`.

## Engineering limits

Defined in [`app/config.py`](app/config.py):

| Measurement | Limit |
|---|---|
| Voltage | 3.0 V ≤ v ≤ 3.6 V |
| Current | ≤ 1.0 A |
| Temperature | ≤ 80 °C |
| Duration | > 0 s |

A test passes only if every check passes. All failing checks are recorded in
`failure_reason`, separated by `; `.

## Tests

```bash
pytest
```

The suite covers evaluation logic (including boundary values such as
3.59/3.60/3.61 V), the SQL layer, every API endpoint with its status codes,
input validation, and the data generator. Tests run against temporary
databases and never touch `test_data.db`.

CI (`.github/workflows/tests.yml`) runs the suite on every push and pull
request across Python 3.11–3.13.

## Docker

```bash
docker build -t engineering-test-platform .
docker run -p 8000:8000 -v etp-data:/data engineering-test-platform
```

Then open <http://localhost:8000/docs>. The database lives in the `/data`
volume. To load simulated data into a running container:

```bash
docker exec <container> python -m scripts.generate_test_data
```

## Simulated data

`python -m scripts.generate_test_data` creates 20 devices × 25 tests
(≈ 88 % pass rate). Options: `--devices`, `--tests-per-device`, `--seed`
(reproducible output), `--db`, `--reset` (clear existing results first).

## Project layout

```text
app/
  main.py        FastAPI routes only
  services.py    PASS/FAIL evaluation and statistics maths (no FastAPI/SQL)
  database.py    All SQL, parameterized
  schemas.py     Pydantic request/response models
  config.py      Limits and settings (DB path via ETP_DB_PATH)
scripts/generate_test_data.py
tests/           test_evaluation.py, test_database.py, test_api.py, test_generator.py
```

## Possible extensions

Real microcontroller data over UART/USB serial, PostgreSQL, a dashboard,
authentication, per-device limits, CSV export, pagination, failure-trend
detection.
