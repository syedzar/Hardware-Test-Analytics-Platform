from functools import cache

import pytest

from app import config


@pytest.fixture(autouse=True)
def sqlite_backend(monkeypatch):
    """Run every test on SQLite unless it asks for Oracle, whatever .env says."""
    monkeypatch.setattr(config, "DB_BACKEND", "sqlite")


@cache
def oracle_problem() -> str | None:
    """Why the Oracle tests cannot run, or None when a database is reachable."""
    try:
        import oracledb
    except ImportError:
        return "python-oracledb is not installed"
    if not (config.ORACLE_USER and config.ORACLE_PASSWORD):
        return "ORACLE_USER and ORACLE_PASSWORD are not set"
    try:
        oracledb.connect(
            user=config.ORACLE_USER,
            password=config.ORACLE_PASSWORD,
            dsn=config.ORACLE_DSN,
            tcp_connect_timeout=3,
        ).close()
    except oracledb.Error as exc:
        return f"Oracle is not reachable at {config.ORACLE_DSN}: {str(exc).splitlines()[0]}"
    return None


@pytest.fixture(scope="session")
def oracle_ready():
    """The Oracle backend module, or a skip when no Oracle database is reachable.

    The Oracle tests rebuild the schema of ORACLE_USER, so any data loaded
    there is removed. Reseed it afterwards with scripts.generate_test_data.
    """
    problem = oracle_problem()
    if problem:
        pytest.skip(problem)

    from app import oracle_db

    yield oracle_db
    oracle_db.close_pool()


@pytest.fixture
def oracle(oracle_ready, monkeypatch):
    """An empty Oracle schema, selected as the active backend."""
    monkeypatch.setattr(config, "DB_BACKEND", "oracle")
    oracle_ready.reset_db()
    return oracle_ready
