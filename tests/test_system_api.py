import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app import datasets as datasets_shim
from app.api.datasets import router as canonical_datasets_router
from app.main import app, create_app


class TestSystemAPI(unittest.TestCase):
    """Tests for system endpoints, database health, application factory, and compatibility."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)

    def test_home_endpoint_returns_welcome_message(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Welcome to DataPilot AI!"})

    def test_database_health_healthy(self):
        mock_connection = MagicMock()
        with patch("app.api.system.engine.connect", return_value=mock_connection):
            mock_connection.__enter__.return_value = mock_connection
            response = self.client.get("/health/db")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {"status": "healthy", "database": "connected"}
            )

    def test_database_health_failure_returns_503(self):
        with patch("app.api.system.engine.connect", side_effect=SQLAlchemyError("Connection refused")):
            response = self.client.get("/health/db")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["detail"], "Database connection failed")

    def test_create_app_factory(self):
        new_app = create_app()
        self.assertIsInstance(new_app, FastAPI)
        self.assertIsNot(new_app, app)

        # Verify client on factory app can access all endpoints
        client = TestClient(new_app, raise_server_exceptions=False)
        self.assertEqual(client.get("/").status_code, 200)
        with patch("app.api.system.engine.connect", return_value=MagicMock()):
            self.assertEqual(client.get("/health/db").status_code, 200)
        self.assertEqual(client.get("/api/datasets/").status_code, 200)

    def test_backward_compatible_datasets_shim(self):
        # 1. Router identity
        self.assertIs(datasets_shim.router, canonical_datasets_router)

        # 2. Re-exported symbols
        expected_symbols = [
            "router",
            "MAX_FILE_SIZE",
            "PROJECT_ROOT",
            "UPLOAD_DIR",
            "inspect_csv",
            "upload_csv",
            "list_datasets",
            "get_dataset",
        ]
        for symbol in expected_symbols:
            self.assertTrue(hasattr(datasets_shim, symbol), f"Missing symbol {symbol} in app.datasets")
            self.assertIn(symbol, datasets_shim.__all__)


if __name__ == "__main__":
    unittest.main()
