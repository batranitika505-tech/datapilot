import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.config import Settings
from app.database import get_database_url


class TestConfiguration(unittest.TestCase):
    """Unit tests for Settings validation, precedence, and database URL resolution."""

    def test_database_url_precedence_over_individual_fields(self):
        explicit_url = "postgresql+psycopg://user_a:pass_a@dbhost:5433/custom_db"
        settings_instance = Settings(
            DATABASE_URL=explicit_url,
            DB_USER="user_b",
            DB_PASSWORD="pass_b",
            DB_HOST="otherhost",
            DB_PORT=5432,
            DB_NAME="other_db",
        )

        with patch("app.database.settings", settings_instance):
            url = get_database_url()
            self.assertEqual(url.username, "user_a")
            self.assertEqual(url.host, "dbhost")
            self.assertEqual(url.port, 5433)
            self.assertEqual(url.database, "custom_db")

    def test_individual_fields_fallback_when_database_url_none(self):
        settings_instance = Settings(
            DATABASE_URL=None,
            DB_USER="user_b",
            DB_PASSWORD="pass_b",
            DB_HOST="customhost",
            DB_PORT=5434,
            DB_NAME="fallback_db",
        )

        with patch("app.database.settings", settings_instance):
            url = get_database_url()
            self.assertEqual(url.drivername, "postgresql+psycopg")
            self.assertEqual(url.username, "user_b")
            self.assertEqual(url.host, "customhost")
            self.assertEqual(url.port, 5434)
            self.assertEqual(url.database, "fallback_db")

    def test_missing_credentials_rejected(self):
        # Neither DATABASE_URL nor DB_USER/DB_PASSWORD supplied
        with self.assertRaises(ValidationError) as ctx:
            Settings(
                DATABASE_URL=None,
                DB_USER=None,
                DB_PASSWORD=None,
                DB_HOST="localhost",
                DB_NAME="test",
            )
        self.assertIn("Either DATABASE_URL or both DB_USER and DB_PASSWORD must be configured", str(ctx.exception))

        # Only DB_USER without DB_PASSWORD
        with self.assertRaises(ValidationError) as ctx:
            Settings(
                DATABASE_URL=None,
                DB_USER="only_user",
                DB_PASSWORD=None,
                DB_HOST="localhost",
                DB_NAME="test",
            )
        self.assertIn("Either DATABASE_URL or both DB_USER and DB_PASSWORD must be configured", str(ctx.exception))

    def test_database_url_only_configuration_allowed(self):
        # DB_USER and DB_PASSWORD omitted, only DATABASE_URL supplied
        settings_instance = Settings(
            DATABASE_URL="postgresql+psycopg://dbuser:dbpass@remotehost:5432/remotedb",
            DB_USER=None,
            DB_PASSWORD=None,
        )
        self.assertEqual(settings_instance.DATABASE_URL, "postgresql+psycopg://dbuser:dbpass@remotehost:5432/remotedb")
        self.assertIsNone(settings_instance.DB_USER)
        self.assertIsNone(settings_instance.DB_PASSWORD)

    def test_port_validation(self):
        # Valid ports
        s1 = Settings(DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/d", DB_PORT=1)
        self.assertEqual(s1.DB_PORT, 1)
        s2 = Settings(DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/d", DB_PORT=65535)
        self.assertEqual(s2.DB_PORT, 65535)

        # Invalid port: 0
        with self.assertRaises(ValidationError):
            Settings(DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/d", DB_PORT=0)

        # Invalid port: > 65535
        with self.assertRaises(ValidationError):
            Settings(DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/d", DB_PORT=65536)

    def test_connection_pool_defaults_and_validation(self):
        s = Settings(DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/d")
        self.assertEqual(s.DB_POOL_SIZE, 5)
        self.assertEqual(s.DB_MAX_OVERFLOW, 10)
        self.assertEqual(s.DB_POOL_TIMEOUT, 30)
        self.assertEqual(s.DB_POOL_RECYCLE, 1800)

        # Invalid pool size (< 1)
        with self.assertRaises(ValidationError):
            Settings(DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/d", DB_POOL_SIZE=0)

        # Invalid pool timeout (< 1)
        with self.assertRaises(ValidationError):
            Settings(DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/d", DB_POOL_TIMEOUT=0)

        # Valid pool recycle boundaries
        s_min = Settings(DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/d", DB_POOL_RECYCLE=60)
        self.assertEqual(s_min.DB_POOL_RECYCLE, 60)
        s_max = Settings(DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/d", DB_POOL_RECYCLE=86400)
        self.assertEqual(s_max.DB_POOL_RECYCLE, 86400)

        # Invalid pool recycle (< 60)
        with self.assertRaises(ValidationError):
            Settings(DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/d", DB_POOL_RECYCLE=59)

        # Invalid pool recycle (> 86400)
        with self.assertRaises(ValidationError):
            Settings(DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/d", DB_POOL_RECYCLE=86401)

    def test_extra_environment_variables_ignored(self):
        with patch.dict(os.environ, {"EXTRA_UNKNOWN_VARIABLE": "ignored_value", "TEST_DATABASE_URL": "custom"}):
            settings_instance = Settings(DATABASE_URL="postgresql+psycopg://u:p@localhost:5432/d")
            self.assertIsNotNone(settings_instance)


if __name__ == "__main__":
    unittest.main()

