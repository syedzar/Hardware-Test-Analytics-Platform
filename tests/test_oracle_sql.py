"""Checks on the Oracle backend that do not need a running database."""

import pytest

from app import config, oracle_db


def test_read_statements_splits_on_slash_lines(tmp_path):
    script = tmp_path / "script.sql"
    script.write_text(
        "-- header comment\n"
        "\n"
        "CREATE TABLE t (\n"
        "    a NUMBER\n"
        ")\n"
        "/\n"
        "\n"
        "-- a block keeps its semicolons, and a division is not a separator\n"
        "BEGIN\n"
        "    x := 100 * a / b;\n"
        "END;\n"
        "/  \n",
        encoding="utf-8",
    )
    assert oracle_db.read_statements(script) == [
        "CREATE TABLE t (\n    a NUMBER\n)",
        "BEGIN\n    x := 100 * a / b;\nEND;",
    ]


def test_read_statements_ignores_comment_only_chunks(tmp_path):
    script = tmp_path / "script.sql"
    script.write_text("-- nothing to run\n/\n\n", encoding="utf-8")
    assert oracle_db.read_statements(script) == []


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("schema.sql", 7),  # 3 tables, 3 indexes, 1 seed MERGE
        ("views.sql", 2),
        ("test_stats_pkg.sql", 2),  # specification and body
        ("drop.sql", 6),
    ],
)
def test_shipped_sql_files_split_into_the_expected_statements(filename, expected):
    statements = oracle_db.read_statements(oracle_db.SQL_DIR / filename)
    assert len(statements) == expected
    for statement in statements:
        is_plsql = statement.startswith("CREATE OR REPLACE PACKAGE")
        assert statement.endswith(";") == is_plsql


def test_oracle_backend_needs_credentials(monkeypatch):
    monkeypatch.setattr(oracle_db, "_pool", None)
    monkeypatch.setattr(config, "ORACLE_PASSWORD", None)
    with pytest.raises(RuntimeError, match="ORACLE_USER and ORACLE_PASSWORD"):
        oracle_db.get_pool()


def test_close_pool_without_a_pool_does_nothing(monkeypatch):
    monkeypatch.setattr(oracle_db, "_pool", None)
    oracle_db.close_pool()
    assert oracle_db._pool is None
