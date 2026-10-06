-- Hardware Test Analytics Platform: PL/SQL package. Run after views.sql.
--
-- test_stats_pkg is the only way the application writes a test result to
-- Oracle, and where it reads its statistics from. None of the routines commit;
-- the caller owns the transaction.

CREATE OR REPLACE PACKAGE test_stats_pkg AS

    -- Application error codes raised by record_test_result.
    c_err_device       CONSTANT PLS_INTEGER := -20001;
    c_err_test_type    CONSTANT PLS_INTEGER := -20002;
    c_err_result       CONSTANT PLS_INTEGER := -20003;
    c_err_measurement  CONSTANT PLS_INTEGER := -20004;

    -- Validate and store one test result, registering the device on first use.
    -- p_tested_at defaults to the current UTC time.
    PROCEDURE record_test_result (
        p_device_code     IN  devices.device_code%TYPE,
        p_test_type       IN  test_types.type_code%TYPE,
        p_voltage_v       IN  test_results.voltage_v%TYPE,
        p_current_a       IN  test_results.current_a%TYPE,
        p_temperature_c   IN  test_results.temperature_c%TYPE,
        p_duration_s      IN  test_results.duration_s%TYPE,
        p_result          IN  test_results.result%TYPE,
        p_failure_reason  IN  test_results.failure_reason%TYPE,
        p_tested_at       IN  test_results.tested_at%TYPE DEFAULT NULL,
        p_result_id       OUT test_results.result_id%TYPE
    );

    -- Pass rate of one device as a percentage rounded to one decimal place.
    -- Returns NULL when the device has no tests.
    FUNCTION device_pass_rate (
        p_device_code  IN devices.device_code%TYPE
    ) RETURN NUMBER;

    -- p_overall: one row of totals and averages across every test.
    -- p_per_device: the same figures per device, ordered by device code.
    PROCEDURE get_statistics (
        p_overall     OUT SYS_REFCURSOR,
        p_per_device  OUT SYS_REFCURSOR
    );

    -- One row of totals and averages for a single device (zero tests if the
    -- device is unknown).
    PROCEDURE get_device_statistics (
        p_device_code  IN  devices.device_code%TYPE,
        p_stats        OUT SYS_REFCURSOR
    );

END test_stats_pkg;
/

CREATE OR REPLACE PACKAGE BODY test_stats_pkg AS

    FUNCTION is_finite (p_value IN BINARY_DOUBLE) RETURN BOOLEAN IS
    BEGIN
        RETURN p_value IS NOT NULL
           AND p_value IS NOT NAN
           AND p_value IS NOT INFINITE;
    END is_finite;

    -- Return the surrogate key for a device code, inserting the device if it
    -- has not been seen before.
    FUNCTION get_or_create_device (
        p_device_code  IN devices.device_code%TYPE
    ) RETURN devices.device_id%TYPE IS
        l_device_id  devices.device_id%TYPE;
    BEGIN
        SELECT device_id INTO l_device_id
        FROM devices
        WHERE device_code = p_device_code;
        RETURN l_device_id;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            BEGIN
                INSERT INTO devices (device_code)
                VALUES (p_device_code)
                RETURNING device_id INTO l_device_id;
            EXCEPTION
                WHEN DUP_VAL_ON_INDEX THEN
                    -- Another session registered the same device first.
                    SELECT device_id INTO l_device_id
                    FROM devices
                    WHERE device_code = p_device_code;
            END;
            RETURN l_device_id;
    END get_or_create_device;

    PROCEDURE record_test_result (
        p_device_code     IN  devices.device_code%TYPE,
        p_test_type       IN  test_types.type_code%TYPE,
        p_voltage_v       IN  test_results.voltage_v%TYPE,
        p_current_a       IN  test_results.current_a%TYPE,
        p_temperature_c   IN  test_results.temperature_c%TYPE,
        p_duration_s      IN  test_results.duration_s%TYPE,
        p_result          IN  test_results.result%TYPE,
        p_failure_reason  IN  test_results.failure_reason%TYPE,
        p_tested_at       IN  test_results.tested_at%TYPE DEFAULT NULL,
        p_result_id       OUT test_results.result_id%TYPE
    ) IS
        l_device_id     devices.device_id%TYPE;
        l_test_type_id  test_types.test_type_id%TYPE;
    BEGIN
        IF p_device_code IS NULL OR LENGTH(p_device_code) > 64 THEN
            RAISE_APPLICATION_ERROR(
                c_err_device, 'Device code must be 1 to 64 characters');
        END IF;

        IF p_result IS NULL OR p_result NOT IN ('PASS', 'FAIL') THEN
            RAISE_APPLICATION_ERROR(c_err_result, 'Result must be PASS or FAIL');
        END IF;

        IF p_result = 'FAIL' AND p_failure_reason IS NULL THEN
            RAISE_APPLICATION_ERROR(
                c_err_result, 'A FAIL result needs a failure reason');
        END IF;

        IF p_result = 'PASS' AND p_failure_reason IS NOT NULL THEN
            RAISE_APPLICATION_ERROR(
                c_err_result, 'A PASS result cannot have a failure reason');
        END IF;

        IF NOT (is_finite(p_voltage_v) AND is_finite(p_current_a)
                AND is_finite(p_temperature_c) AND is_finite(p_duration_s)) THEN
            RAISE_APPLICATION_ERROR(
                c_err_measurement, 'Measurements must be finite numbers');
        END IF;

        IF p_duration_s < 0 THEN
            RAISE_APPLICATION_ERROR(
                c_err_measurement, 'Duration cannot be negative');
        END IF;

        BEGIN
            SELECT test_type_id INTO l_test_type_id
            FROM test_types
            WHERE type_code = p_test_type;
        EXCEPTION
            WHEN NO_DATA_FOUND THEN
                RAISE_APPLICATION_ERROR(
                    c_err_test_type, 'Unknown test type: ' || p_test_type);
        END;

        l_device_id := get_or_create_device(p_device_code);

        INSERT INTO test_results (
            device_id, test_type_id, voltage_v, current_a, temperature_c,
            duration_s, result, failure_reason, tested_at
        )
        VALUES (
            l_device_id, l_test_type_id, p_voltage_v, p_current_a,
            p_temperature_c, p_duration_s, p_result, p_failure_reason,
            COALESCE(p_tested_at, SYS_EXTRACT_UTC(SYSTIMESTAMP))
        )
        RETURNING result_id INTO p_result_id;
    END record_test_result;

    FUNCTION device_pass_rate (
        p_device_code  IN devices.device_code%TYPE
    ) RETURN NUMBER IS
        l_total   PLS_INTEGER;
        l_passed  PLS_INTEGER;
    BEGIN
        SELECT COUNT(*), COALESCE(SUM(passed), 0)
        INTO l_total, l_passed
        FROM v_test_report
        WHERE device_code = p_device_code;

        IF l_total = 0 THEN
            RETURN NULL;
        END IF;
        RETURN ROUND(100 * l_passed / l_total, 1);
    END device_pass_rate;

    PROCEDURE get_statistics (
        p_overall     OUT SYS_REFCURSOR,
        p_per_device  OUT SYS_REFCURSOR
    ) IS
    BEGIN
        OPEN p_overall FOR
            SELECT
                COUNT(*) AS total_tests,
                COALESCE(SUM(passed), 0) AS passed_tests,
                COALESCE(SUM(failed), 0) AS failed_tests,
                AVG(voltage_v) AS average_voltage,
                AVG(current_a) AS average_current,
                AVG(temperature_c) AS average_temperature
            FROM v_test_report;

        OPEN p_per_device FOR
            SELECT
                device_code AS device_id,
                COUNT(*) AS total_tests,
                SUM(passed) AS passed_tests,
                SUM(failed) AS failed_tests,
                ROUND(100 * SUM(passed) / COUNT(*), 1) AS pass_rate,
                AVG(voltage_v) AS average_voltage,
                AVG(current_a) AS average_current,
                AVG(temperature_c) AS average_temperature
            FROM v_test_report
            GROUP BY device_code
            ORDER BY device_code;
    END get_statistics;

    PROCEDURE get_device_statistics (
        p_device_code  IN  devices.device_code%TYPE,
        p_stats        OUT SYS_REFCURSOR
    ) IS
    BEGIN
        OPEN p_stats FOR
            SELECT
                COUNT(*) AS total_tests,
                COALESCE(SUM(passed), 0) AS passed_tests,
                COALESCE(SUM(failed), 0) AS failed_tests,
                AVG(voltage_v) AS average_voltage,
                AVG(current_a) AS average_current,
                AVG(temperature_c) AS average_temperature
            FROM v_test_report
            WHERE device_code = p_device_code;
    END get_device_statistics;

END test_stats_pkg;
/
