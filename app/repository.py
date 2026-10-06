"""Chooses the data-access backend.

Both backends expose the same functions (``init_db``, ``insert_test``,
``get_test``, ``get_all_tests``, ``get_device_tests``, ``get_failed_tests``,
``delete_test``, ``get_statistics``, ``get_device_statistics``,
``get_report_rows`` and ``reset_db``) and return records in the same shape,
so the routes and scripts do not need to know which database is behind them.
"""

from app import config, database

SQLITE = "sqlite"
ORACLE = "oracle"


def get_backend(name: str | None = None):
    """Return the backend module for ``name``, or for ``DB_BACKEND`` by default.

    The setting is read at call time. The Oracle module is imported only when
    it is asked for, so the SQLite backend works without the Oracle driver.
    """
    name = (name or config.DB_BACKEND).strip().lower()
    if name == SQLITE:
        return database
    if name == ORACLE:
        from app import oracle_db

        return oracle_db
    raise ValueError(f"Unknown DB_BACKEND {name!r}; expected 'sqlite' or 'oracle'")
