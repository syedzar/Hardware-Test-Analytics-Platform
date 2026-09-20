from app import database
from scripts.generate_test_data import generate


def test_generator_creates_expected_number_of_tests(tmp_path):
    db_path = str(tmp_path / "generated.db")
    database.init_db(db_path)
    generate(devices=20, tests_per_device=25, seed=1, db_path=db_path)

    stats = database.get_statistics(db_path)
    assert stats["total_tests"] == 500
    assert stats["passed_tests"] > 0
    assert stats["failed_tests"] > 0
    assert len(database.get_device_tests("FPGA-020", db_path)) == 25


def test_generator_is_reproducible_with_a_seed(tmp_path):
    def run(name):
        path = str(tmp_path / name)
        database.init_db(path)
        generate(devices=3, tests_per_device=5, seed=42, db_path=path)
        return [
            {k: v for k, v in row.items() if k not in ("id", "timestamp")}
            for row in database.get_all_tests(path)
        ]

    assert run("a.db") == run("b.db")
