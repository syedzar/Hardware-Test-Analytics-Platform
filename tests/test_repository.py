import pytest

from app import config, database, oracle_db, repository


def test_sqlite_is_the_default_backend():
    assert repository.get_backend() is database


def test_backend_follows_the_setting_at_call_time(monkeypatch):
    monkeypatch.setattr(config, "DB_BACKEND", "oracle")
    assert repository.get_backend() is oracle_db


def test_backend_can_be_named_explicitly():
    assert repository.get_backend("sqlite") is database
    assert repository.get_backend(" Oracle ") is oracle_db


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError, match="Unknown DB_BACKEND 'postgres'"):
        repository.get_backend("postgres")


@pytest.mark.parametrize(
    "name",
    [
        "init_db",
        "reset_db",
        "insert_test",
        "get_test",
        "get_all_tests",
        "get_device_tests",
        "get_failed_tests",
        "delete_test",
        "get_statistics",
        "get_device_statistics",
        "get_report_rows",
    ],
)
def test_both_backends_expose_the_same_functions(name):
    assert callable(getattr(database, name))
    assert callable(getattr(oracle_db, name))
