import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import app.api.datasets
from app.database import DATABASE_URL
from app.models import Dataset

try:
    from tests.fixtures import (
        DatasetAPITestBase,
        create_corrupt_csv_content,
        create_empty_csv_content,
        create_large_csv_content,
        create_valid_csv_content,
        create_whitespace_csv_content,
        get_test_database_url,
    )
except ImportError:
    from fixtures import (
        DatasetAPITestBase,
        create_corrupt_csv_content,
        create_empty_csv_content,
        create_large_csv_content,
        create_valid_csv_content,
        create_whitespace_csv_content,
        get_test_database_url,
    )


class TestCSVUploadAPI(unittest.TestCase, DatasetAPITestBase):
    """Integration tests for POST /api/datasets/upload endpoint."""

    @classmethod
    def setUpClass(cls):
        cls.init_test_database()

    @classmethod
    def tearDownClass(cls):
        cls.teardown_test_database()

    def setUp(self):
        self.setup_temp_storage_and_db()

    def tearDown(self):
        self.teardown_temp_storage_and_db()

    def test_valid_csv_upload_returns_201_and_expected_fields(self):
        csv_content = create_valid_csv_content()
        response = self.client.post(
            "/api/datasets/upload",
            files={"file": ("employees.csv", csv_content, "text/csv")}
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()

        # Verify expected fields in response
        expected_keys = {
            "id", "filename", "total_rows", "total_columns",
            "columns", "profile", "created_at"
        }
        self.assertTrue(expected_keys.issubset(data.keys()))

        # Verify field contents
        self.assertEqual(data["filename"], "employees.csv")
        self.assertEqual(data["total_rows"], 3)
        self.assertEqual(data["total_columns"], 4)

        # Verify columns schema
        column_names = [col["name"] for col in data["columns"]]
        self.assertEqual(column_names, ["name", "age", "salary", "city"])

        # Verify profile schema
        profile = data["profile"]
        self.assertEqual(profile["total_missing_values"], 0)
        self.assertEqual(profile["duplicate_rows"], 0)
        self.assertEqual(len(profile["columns"]), 4)

    def test_valid_csv_metadata_persisted_in_database(self):
        csv_content = create_valid_csv_content()
        response = self.client.post(
            "/api/datasets/upload",
            files={"file": ("employees.csv", csv_content, "text/csv")}
        )
        self.assertEqual(response.status_code, 201)
        dataset_id = uuid.UUID(response.json()["id"])

        # Query database directly using test session
        with self.TestingSessionLocal() as session:
            dataset = session.get(Dataset, dataset_id)

            self.assertIsNotNone(dataset)
            self.assertEqual(dataset.id, dataset_id)
            self.assertEqual(dataset.filename, "employees.csv")
            self.assertEqual(dataset.total_rows, 3)
            self.assertEqual(dataset.total_columns, 4)
            self.assertEqual(len(dataset.columns), 4)
            self.assertEqual(dataset.profile["total_missing_values"], 0)
            self.assertEqual(dataset.profile["duplicate_rows"], 0)
            self.assertIsNotNone(dataset.created_at)

    def test_valid_csv_file_stored_successfully_on_disk(self):
        csv_content = create_valid_csv_content()
        response = self.client.post(
            "/api/datasets/upload",
            files={"file": ("employees.csv", csv_content, "text/csv")}
        )
        self.assertEqual(response.status_code, 201)
        dataset_id = response.json()["id"]

        # Check file exists in isolated temp upload directory
        stored_file_path = self.temp_upload_dir / f"{dataset_id}.csv"
        self.assertTrue(stored_file_path.exists())
        self.assertTrue(stored_file_path.is_file())

        # Check contents match exactly
        self.assertEqual(stored_file_path.read_bytes(), csv_content)

        # Check database relative storage path
        with self.TestingSessionLocal() as session:
            dataset = session.get(Dataset, uuid.UUID(dataset_id))
            self.assertEqual(dataset.storage_path, f"data/uploads/{dataset_id}.csv")

    def test_upload_csv_with_upload_dir_outside_project_root(self):
        """
        Regression test for Milestone 1.3:
        Verifies that when UPLOAD_DIR is located outside PROJECT_ROOT,
        the upload succeeds (HTTP 201), the file is stored at the external
        path, and storage_path in the database is recorded without raising ValueError.
        """
        csv_content = create_valid_csv_content()

        with tempfile.TemporaryDirectory() as outside_temp_dir:
            outside_upload_dir = Path(outside_temp_dir) / "custom_uploads"
            with patch.object(app.api.datasets, "UPLOAD_DIR", outside_upload_dir):
                response = self.client.post(
                    "/api/datasets/upload",
                    files={"file": ("outside.csv", csv_content, "text/csv")}
                )

                self.assertEqual(response.status_code, 201)
                data = response.json()
                dataset_id = uuid.UUID(data["id"])

                # Check file exists in outside upload dir
                stored_file_path = outside_upload_dir / f"{dataset_id}.csv"
                self.assertTrue(stored_file_path.exists())
                self.assertTrue(stored_file_path.is_file())
                self.assertEqual(stored_file_path.read_bytes(), csv_content)

                # Check database storage_path records the resolved external path
                with self.TestingSessionLocal() as session:
                    dataset = session.get(Dataset, dataset_id)
                    self.assertIsNotNone(dataset)
                    self.assertEqual(dataset.filename, "outside.csv")
                    self.assertEqual(dataset.storage_path, str(stored_file_path.resolve()))
                    self.assertTrue(Path(dataset.storage_path).is_absolute())


class TestDatasetListingAPI(unittest.TestCase, DatasetAPITestBase):
    """Integration tests for GET /api/datasets/ endpoint."""

    @classmethod
    def setUpClass(cls):
        cls.init_test_database()

    @classmethod
    def tearDownClass(cls):
        cls.teardown_test_database()

    def setUp(self):
        self.setup_temp_storage_and_db()

    def tearDown(self):
        self.teardown_temp_storage_and_db()

    def test_list_datasets_empty(self):
        response = self.client.get("/api/datasets/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_datasets_returns_persisted_datasets(self):
        dataset1 = self.create_persisted_dataset(filename="ds1.csv", total_rows=10, total_columns=2)
        dataset2 = self.create_persisted_dataset(filename="ds2.csv", total_rows=20, total_columns=5)

        response = self.client.get("/api/datasets/")

        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertEqual(len(items), 2)

        returned_ids = {item["id"] for item in items}
        self.assertEqual(returned_ids, {str(dataset1.id), str(dataset2.id)})

    def test_list_datasets_metadata_fields(self):
        dataset = self.create_persisted_dataset(
            filename="sales.csv",
            total_rows=100,
            total_columns=8
        )

        response = self.client.get("/api/datasets/")

        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertEqual(len(items), 1)

        item = items[0]
        self.assertEqual(item["id"], str(dataset.id))
        self.assertEqual(item["filename"], "sales.csv")
        self.assertEqual(item["total_rows"], 100)
        self.assertEqual(item["total_columns"], 8)
        self.assertIn("created_at", item)
        # Verify columns and profile are not exposed in summary
        self.assertNotIn("columns", item)
        self.assertNotIn("profile", item)


class TestDatasetDetailAPI(unittest.TestCase, DatasetAPITestBase):
    """Integration tests for GET /api/datasets/{dataset_id} endpoint."""

    @classmethod
    def setUpClass(cls):
        cls.init_test_database()

    @classmethod
    def tearDownClass(cls):
        cls.teardown_test_database()

    def setUp(self):
        self.setup_temp_storage_and_db()

    def tearDown(self):
        self.teardown_temp_storage_and_db()

    def test_get_dataset_detail_success(self):
        columns = [
            {"name": "id", "data_type": "int64"},
            {"name": "product", "data_type": "object"}
        ]
        profile = {
            "total_rows": 5,
            "total_columns": 2,
            "total_missing_values": 0,
            "duplicate_rows": 0,
            "columns": []
        }
        dataset = self.create_persisted_dataset(
            filename="inventory.csv",
            total_rows=5,
            total_columns=2,
            columns=columns,
            profile=profile
        )

        response = self.client.get(f"/api/datasets/{dataset.id}")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["id"], str(dataset.id))
        self.assertEqual(data["filename"], "inventory.csv")
        self.assertEqual(data["total_rows"], 5)
        self.assertEqual(data["total_columns"], 2)
        self.assertEqual(data["columns"], columns)
        self.assertEqual(data["profile"], profile)
        self.assertIn("created_at", data)

    def test_get_dataset_unknown_uuid_returns_404(self):
        unknown_id = uuid.uuid4()
        response = self.client.get(f"/api/datasets/{unknown_id}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Dataset not found")

    def test_get_dataset_invalid_uuid_returns_422(self):
        response = self.client.get("/api/datasets/not-a-valid-uuid")

        self.assertEqual(response.status_code, 422)


class TestDatasetInvalidUploadsAPI(unittest.TestCase, DatasetAPITestBase):
    """Integration tests for invalid upload scenarios and verifying no files remain."""

    @classmethod
    def setUpClass(cls):
        cls.init_test_database()

    @classmethod
    def tearDownClass(cls):
        cls.teardown_test_database()

    def setUp(self):
        self.setup_temp_storage_and_db()

    def tearDown(self):
        self.teardown_temp_storage_and_db()

    def test_non_csv_file_returns_400_and_leaves_no_files(self):
        invalid_filenames = [
            "data.txt",
            "document.pdf",
            "records.json",
            "data.csv.bak",
            "noextension"
        ]

        for filename in invalid_filenames:
            with self.subTest(filename=filename):
                response = self.client.post(
                    "/api/datasets/upload",
                    files={"file": (filename, b"a,b,c\n1,2,3", "text/plain")}
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["detail"], "Only CSV files are allowed")
                self.assertEqual(self.count_files_in_upload_dir(), 0)
                self.assertEqual(self.count_datasets_in_db(), 0)

    def test_filename_exceeding_255_chars_returns_400(self):
        long_filename = "a" * 252 + ".csv"  # 256 characters
        response = self.client.post(
            "/api/datasets/upload",
            files={"file": (long_filename, b"a,b\n1,2", "text/csv")}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Filename must not exceed 255 characters")
        self.assertEqual(self.count_files_in_upload_dir(), 0)
        self.assertEqual(self.count_datasets_in_db(), 0)

    def test_empty_file_returns_400_and_leaves_no_files(self):
        empty_content = create_empty_csv_content()
        response = self.client.post(
            "/api/datasets/upload",
            files={"file": ("empty.csv", empty_content, "text/csv")}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Uploaded file is empty")
        self.assertEqual(self.count_files_in_upload_dir(), 0)
        self.assertEqual(self.count_datasets_in_db(), 0)

    def test_whitespace_only_csv_returns_400_and_leaves_no_files(self):
        whitespace_content = create_whitespace_csv_content()
        response = self.client.post(
            "/api/datasets/upload",
            files={"file": ("blank.csv", whitespace_content, "text/csv")}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "CSV contains no data or column headers")
        self.assertEqual(self.count_files_in_upload_dir(), 0)
        self.assertEqual(self.count_datasets_in_db(), 0)

    def test_corrupt_csv_returns_400_and_leaves_no_files(self):
        corrupt_content = create_corrupt_csv_content()
        response = self.client.post(
            "/api/datasets/upload",
            files={"file": ("corrupt.csv", corrupt_content, "text/csv")}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Invalid CSV format or encoding")
        self.assertEqual(self.count_files_in_upload_dir(), 0)
        self.assertEqual(self.count_datasets_in_db(), 0)

    def test_file_larger_than_10mb_returns_413_and_leaves_no_files(self):
        # 10 MB + 1 KB
        large_content = create_large_csv_content(10 * 1024 * 1024 + 1024)
        response = self.client.post(
            "/api/datasets/upload",
            files={"file": ("large.csv", large_content, "text/csv")}
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"], "File size must not exceed 10 MB")
        self.assertEqual(self.count_files_in_upload_dir(), 0)
        self.assertEqual(self.count_datasets_in_db(), 0)


class TestDatasetDatabaseFailureAPI(unittest.TestCase, DatasetAPITestBase):
    """Integration tests simulating database commit failure during upload."""

    @classmethod
    def setUpClass(cls):
        cls.init_test_database()

    @classmethod
    def tearDownClass(cls):
        cls.teardown_test_database()

    def setUp(self):
        self.setup_temp_storage_and_db()

    def tearDown(self):
        self.teardown_temp_storage_and_db()

    def test_database_commit_failure_returns_500_and_cleans_up(self):
        csv_content = create_valid_csv_content()

        rollback_called = False
        original_rollback = Session.rollback

        def spy_rollback(session_self, *args, **kwargs):
            nonlocal rollback_called
            rollback_called = True
            return original_rollback(session_self, *args, **kwargs)

        with patch.object(Session, "commit", side_effect=SQLAlchemyError("Simulated database failure")):
            with patch.object(Session, "rollback", spy_rollback):
                response = self.client.post(
                    "/api/datasets/upload",
                    files={"file": ("test_fail.csv", csv_content, "text/csv")}
                )

                # 1. Verify API returns HTTP 500
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.json()["detail"], "Failed to save dataset metadata")

                # 2. Verify database rollback occurred and real rollback executed
                self.assertTrue(rollback_called)

                # 3. Verify uploaded file is cleaned up from disk
                self.assertEqual(self.count_files_in_upload_dir(), 0)

                # 4. Verify transaction was rolled back and no record was saved in DB
                self.assertEqual(self.count_datasets_in_db(), 0)

    def test_list_datasets_database_failure_returns_500(self):
        with patch.object(Session, "execute", side_effect=SQLAlchemyError("Simulated list query failure")):
            response = self.client.get("/api/datasets/")
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.headers["content-type"], "application/json")
            self.assertEqual(response.json()["detail"], "Failed to retrieve datasets")

    def test_get_dataset_database_failure_returns_500(self):
        valid_id = uuid.uuid4()
        with patch.object(Session, "get", side_effect=SQLAlchemyError("Simulated get query failure")):
            response = self.client.get(f"/api/datasets/{valid_id}")
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.headers["content-type"], "application/json")
            self.assertEqual(response.json()["detail"], "Failed to retrieve dataset")

    def test_unexpected_exception_returns_json_500(self):
        from fastapi.testclient import TestClient
        from app.main import app as fastapi_app

        client = TestClient(fastapi_app, raise_server_exceptions=False)
        with patch("app.services.dataset.list_datasets", side_effect=RuntimeError("Unexpected unhandled internal error")):
            response = client.get("/api/datasets/")
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.headers["content-type"], "application/json")
            self.assertEqual(response.json(), {"detail": "Internal server error"})


class TestDatasetTestDatabaseSafety(unittest.TestCase):
    """Tests ensuring test database isolation and safety constraints."""

    def test_missing_test_database_url_raises_clear_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                get_test_database_url()

            self.assertIn("TEST_DATABASE_URL environment variable is not configured", str(ctx.exception))

    def test_dev_database_url_rejected_for_safety(self):
        # 1. Test database name must end in '_test'
        with patch.dict(os.environ, {"TEST_DATABASE_URL": "postgresql+psycopg://user:secret@localhost:5432/datapilot"}):
            with self.assertRaises(RuntimeError) as ctx:
                get_test_database_url()

            self.assertIn("must end in '_test'", str(ctx.exception))
            self.assertNotIn("secret", str(ctx.exception))

        # 2. Normalized identity comparison: reject dev database even with alternate URL formatting
        variations = [
            str(DATABASE_URL),
            "postgresql://postgres:secret123@127.0.0.1:5432/datapilot",
            "postgresql+psycopg://postgres:secret123@localhost/datapilot",
            "postgresql://postgres:secret123@localhost:5432/datapilot",
        ]
        for url in variations:
            with self.subTest(url=url):
                with patch.dict(os.environ, {"TEST_DATABASE_URL": url}):
                    with self.assertRaises(RuntimeError) as ctx:
                        get_test_database_url()

                    self.assertNotIn("secret123", str(ctx.exception))
                    self.assertNotIn("postgres123", str(ctx.exception))

        # 3. Development database ending in _test rejected via normalized identity comparison
        dev_url = make_url(DATABASE_URL)
        test_url = dev_url.set(database=f"{dev_url.database}_test")
        with patch("tests.fixtures.DATABASE_URL", test_url):
            alt_dev_test_url = f"postgresql://{dev_url.username}:hiddenpass@127.0.0.1:5432/{dev_url.database}_test"
            with patch.dict(os.environ, {"TEST_DATABASE_URL": alt_dev_test_url}):
                with self.assertRaises(RuntimeError) as ctx:
                    get_test_database_url()

                self.assertIn("points to the application's development database", str(ctx.exception))
                self.assertNotIn("hiddenpass", str(ctx.exception))

            # 4. Matching host + port + database rejected even with different username
            alt_dev_test_diff_user = f"postgresql://different_user:hiddenpass@127.0.0.1:5432/{dev_url.database}_test"
            with patch.dict(os.environ, {"TEST_DATABASE_URL": alt_dev_test_diff_user}):
                with self.assertRaises(RuntimeError) as ctx:
                    get_test_database_url()

                self.assertIn("points to the application's development database", str(ctx.exception))
                self.assertNotIn("hiddenpass", str(ctx.exception))

        # 5. Unparseable development DATABASE_URL raises sanitized error with suppressed chaining
        with patch("tests.fixtures.DATABASE_URL", ":::invalid-url:::"):
            with patch.dict(os.environ, {"TEST_DATABASE_URL": "postgresql+psycopg://user:pass@localhost:5432/valid_test"}):
                with self.assertRaises(RuntimeError) as ctx:
                    get_test_database_url()

                self.assertIn("Application development database URL cannot be parsed", str(ctx.exception))
                self.assertIsNone(ctx.exception.__cause__)
                self.assertTrue(ctx.exception.__suppress_context__)


if __name__ == "__main__":
    unittest.main()
