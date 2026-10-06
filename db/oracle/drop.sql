-- Hardware Test Analytics Platform: remove every Oracle object the project
-- creates. Used by reset_db() before the schema is rebuilt. All data is lost.

DROP PACKAGE IF EXISTS test_stats_pkg
/

DROP VIEW IF EXISTS v_failed_tests
/

DROP VIEW IF EXISTS v_test_report
/

DROP TABLE IF EXISTS test_results PURGE
/

DROP TABLE IF EXISTS test_types PURGE
/

DROP TABLE IF EXISTS devices PURGE
/
