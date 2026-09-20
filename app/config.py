"""Central configuration: engineering limits and application settings."""

import os

# Engineering limits used to decide PASS / FAIL.
MIN_VOLTAGE = 3.0  # volts
MAX_VOLTAGE = 3.6  # volts
MAX_CURRENT = 1.0  # amperes
MAX_TEMPERATURE = 80.0  # degrees Celsius
MIN_DURATION_EXCLUSIVE = 0.0  # seconds; duration must be strictly greater

# Path of the SQLite database file. Override with the HTAP_DB_PATH env variable.
DATABASE_PATH = os.environ.get("HTAP_DB_PATH", "test_data.db")
