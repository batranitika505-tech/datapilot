import asyncio
import unittest
from unittest.mock import MagicMock, patch

from app.config import settings
from app.database import engine, get_db
from app.main import app, lifespan


class TestDatabaseLifecycle(unittest.TestCase):
    """Unit and lifecycle tests for database sessions, connection pooling, and engine disposal."""

    def test_get_db_yields_session_and_closes_normally(self):
        mock_session = MagicMock()
        with patch("app.database.SessionLocal", return_value=mock_session):
            gen = get_db()
            db = next(gen)
            self.assertIs(db, mock_session)
            self.assertFalse(mock_session.close.called)
            self.assertFalse(mock_session.rollback.called)

            # Normal completion (request finish)
            with self.assertRaises(StopIteration):
                next(gen)

            self.assertTrue(mock_session.close.called)
            self.assertFalse(mock_session.rollback.called)

    def test_get_db_rolls_back_on_unhandled_exception(self):
        mock_session = MagicMock()
        with patch("app.database.SessionLocal", return_value=mock_session):
            gen = get_db()
            db = next(gen)
            self.assertIs(db, mock_session)

            # Simulate an unhandled exception bubbling through the request dependency
            with self.assertRaises(RuntimeError) as ctx:
                gen.throw(RuntimeError("Unhandled route exception"))

            self.assertEqual(str(ctx.exception), "Unhandled route exception")
            self.assertTrue(mock_session.rollback.called)
            self.assertTrue(mock_session.close.called)

    def test_engine_pool_configuration_applied(self):
        pool = engine.pool
        self.assertEqual(pool.size(), settings.DB_POOL_SIZE)
        self.assertEqual(pool._max_overflow, settings.DB_MAX_OVERFLOW)
        self.assertEqual(pool._timeout, settings.DB_POOL_TIMEOUT)
        self.assertEqual(pool._recycle, settings.DB_POOL_RECYCLE)

    def test_lifespan_disposes_engine_on_shutdown(self):
        async def run_lifespan_test():
            with patch("app.main.engine.dispose") as mock_dispose:
                async with lifespan(app):
                    self.assertFalse(mock_dispose.called)
                self.assertTrue(mock_dispose.called)

        asyncio.run(run_lifespan_test())

    def test_lifespan_disposes_engine_on_exception(self):
        async def run_lifespan_exception_test():
            with patch("app.main.engine.dispose") as mock_dispose:
                with self.assertRaises(RuntimeError):
                    async with lifespan(app):
                        raise RuntimeError("Application startup or runtime error")
                self.assertTrue(mock_dispose.called)

        asyncio.run(run_lifespan_exception_test())


if __name__ == "__main__":
    unittest.main()

