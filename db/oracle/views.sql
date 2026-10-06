-- Hardware Test Analytics Platform: Oracle views. Run after schema.sql.

-- One flat row per test with the device and test type joined in, 1/0 pass and
-- fail flags, and one flag per kind of fault. The fault flags are read from
-- the stored failure reason, so the engineering limits are not repeated here.
CREATE OR REPLACE VIEW v_test_report AS
SELECT
    r.result_id,
    d.device_code,
    t.type_code AS test_type,
    r.result,
    CASE WHEN r.result = 'PASS' THEN 1 ELSE 0 END AS passed,
    CASE WHEN r.result = 'FAIL' THEN 1 ELSE 0 END AS failed,
    r.voltage_v,
    r.current_a,
    r.temperature_c,
    r.duration_s,
    CASE WHEN INSTR(r.failure_reason, 'Voltage') > 0 THEN 1 ELSE 0 END AS voltage_fault,
    CASE WHEN INSTR(r.failure_reason, 'Current') > 0 THEN 1 ELSE 0 END AS current_fault,
    CASE WHEN INSTR(r.failure_reason, 'Temperature') > 0 THEN 1 ELSE 0 END AS temperature_fault,
    CASE WHEN INSTR(r.failure_reason, 'Duration') > 0 THEN 1 ELSE 0 END AS duration_fault,
    r.failure_reason,
    r.tested_at,
    TRUNC(r.tested_at) AS test_date
FROM test_results r
JOIN devices d ON d.device_id = r.device_id
JOIN test_types t ON t.test_type_id = r.test_type_id
WITH READ ONLY
/

-- Failed tests only, in the same shape as v_test_report.
CREATE OR REPLACE VIEW v_failed_tests AS
SELECT
    result_id,
    device_code,
    test_type,
    result,
    passed,
    failed,
    voltage_v,
    current_a,
    temperature_c,
    duration_s,
    voltage_fault,
    current_fault,
    temperature_fault,
    duration_fault,
    failure_reason,
    tested_at,
    test_date
FROM v_test_report
WHERE result = 'FAIL'
WITH READ ONLY
/
