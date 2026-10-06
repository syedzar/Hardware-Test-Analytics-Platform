"""Central configuration: engineering limits and application settings."""

import os

from dotenv import load_dotenv

# Read a local .env file if there is one. Real environment variables win.
load_dotenv()

# Engineering limits used to decide PASS / FAIL.
MIN_VOLTAGE = 3.0  # volts
MAX_VOLTAGE = 3.6  # volts
MAX_CURRENT = 1.0  # amperes
MAX_TEMPERATURE = 80.0  # degrees Celsius
MIN_DURATION_EXCLUSIVE = 0.0  # seconds; duration must be strictly greater

# Which data-access backend to use: "sqlite" (default) or "oracle".
DB_BACKEND = os.environ.get("DB_BACKEND", "sqlite").strip().lower()

# Path of the SQLite database file. Override with the HTAP_DB_PATH env variable.
DATABASE_PATH = os.environ.get("HTAP_DB_PATH", "test_data.db")

# Oracle connection settings. There are no defaults for the credentials, so
# they must come from the environment (see .env.example).
ORACLE_USER = os.environ.get("ORACLE_USER")
ORACLE_PASSWORD = os.environ.get("ORACLE_PASSWORD")
ORACLE_DSN = os.environ.get("ORACLE_DSN", "localhost:1521/FREEPDB1")
