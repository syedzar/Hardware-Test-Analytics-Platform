-- Hardware Test Analytics Platform: Oracle schema (Oracle Database Free, release 23 or later).
--
-- Run as the application user. Every statement ends with a "/" line, so the
-- file works in SQL*Plus and can also be split and run by
-- app/oracle_db.py. It is safe to run more than once.
--
-- Three tables in third normal form:
--   devices       one row per device under test
--   test_types    lookup of the supported kinds of test
--   test_results  one row per test, pointing at a device and a test type

CREATE TABLE IF NOT EXISTS devices (
    device_id    NUMBER GENERATED ALWAYS AS IDENTITY,
    device_code  VARCHAR2(64 CHAR) NOT NULL,
    created_at   TIMESTAMP(0) DEFAULT SYS_EXTRACT_UTC(SYSTIMESTAMP) NOT NULL,
    CONSTRAINT pk_devices PRIMARY KEY (device_id),
    CONSTRAINT uq_devices_code UNIQUE (device_code)
)
/

CREATE TABLE IF NOT EXISTS test_types (
    test_type_id  NUMBER GENERATED ALWAYS AS IDENTITY,
    type_code     VARCHAR2(16 CHAR) NOT NULL,
    CONSTRAINT pk_test_types PRIMARY KEY (test_type_id),
    CONSTRAINT uq_test_types_code UNIQUE (type_code)
)
/

-- Measurements are BINARY_DOUBLE (IEEE 754) so a value stored through the API
-- reads back exactly as it does from the SQLite backend's REAL columns.
CREATE TABLE IF NOT EXISTS test_results (
    result_id       NUMBER GENERATED ALWAYS AS IDENTITY,
    device_id       NUMBER NOT NULL,
    test_type_id    NUMBER NOT NULL,
    voltage_v       BINARY_DOUBLE NOT NULL,
    current_a       BINARY_DOUBLE NOT NULL,
    temperature_c   BINARY_DOUBLE NOT NULL,
    duration_s      BINARY_DOUBLE NOT NULL,
    result          VARCHAR2(4 CHAR) NOT NULL,
    failure_reason  VARCHAR2(500 CHAR),
    tested_at       TIMESTAMP(0) NOT NULL,
    CONSTRAINT pk_test_results PRIMARY KEY (result_id),
    CONSTRAINT fk_results_device FOREIGN KEY (device_id)
        REFERENCES devices (device_id),
    CONSTRAINT fk_results_test_type FOREIGN KEY (test_type_id)
        REFERENCES test_types (test_type_id),
    CONSTRAINT ck_results_result CHECK (result IN ('PASS', 'FAIL')),
    CONSTRAINT ck_results_reason CHECK (
        (result = 'PASS' AND failure_reason IS NULL)
        OR (result = 'FAIL' AND failure_reason IS NOT NULL)
    ),
    CONSTRAINT ck_results_duration CHECK (duration_s >= 0),
    CONSTRAINT ck_results_finite CHECK (
        voltage_v IS NOT NAN AND voltage_v IS NOT INFINITE
        AND current_a IS NOT NAN AND current_a IS NOT INFINITE
        AND temperature_c IS NOT NAN AND temperature_c IS NOT INFINITE
        AND duration_s IS NOT NAN AND duration_s IS NOT INFINITE
    )
)
/

-- Covers the device foreign key and lets per-device pass and fail counts be
-- answered from the index alone.
CREATE INDEX IF NOT EXISTS ix_results_device_result
    ON test_results (device_id, result)
/

-- Covers the test type foreign key.
CREATE INDEX IF NOT EXISTS ix_results_test_type
    ON test_results (test_type_id)
/

-- Supports date-range filters in reports.
CREATE INDEX IF NOT EXISTS ix_results_tested_at
    ON test_results (tested_at)
/

-- Seed the lookup table. MERGE keeps the script repeatable.
MERGE INTO test_types t
USING (
    SELECT 'POWER' AS type_code FROM dual
    UNION ALL SELECT 'UART' FROM dual
    UNION ALL SELECT 'MEMORY' FROM dual
    UNION ALL SELECT 'THERMAL' FROM dual
    UNION ALL SELECT 'FUNCTIONAL' FROM dual
) s
ON (t.type_code = s.type_code)
WHEN NOT MATCHED THEN
    INSERT (type_code) VALUES (s.type_code)
/
