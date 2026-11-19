from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import SQLAlchemyError

from app.models import Dataset
from app.services.dataset import (
    DatasetDatabaseError,
    DatasetStorageError,
    DatasetValidationError,
    create_dataset,
    get_dataset,
    inspect_dataset,
    list_datasets,
    parse_and_profile_csv,
)

try:
    from tests.fixtures import (
        DatasetAPITestBase,
        create_corrupt_csv_content,
        create_valid_csv_content,
        create_whitespace_csv_content,
    )
except ImportError:
    from fixtures import (
        DatasetAPITestBase,
        create_corrupt_csv_content,
        create_valid_csv_content,
        create_whitespace_csv_content,
    )


class TestDatasetServiceParsing(unittest.TestCase):
    """Unit tests for service CSV parsing, profiling, and validation."""

    def test_parse_and_profile_csv_valid(self):
        content = create_valid_csv_content()
        df, columns, profile = parse_and_profile_csv(content)

        self.assertEqual(len(df), 3)
        self.assertEqual(len(columns), 4)
        self.assertEqual([c["name"] for c in columns], ["name", "age", "salary", "city"])
        self.assertEqual(profile["total_missing_values"], 0)
        self.assertEqual(profile["duplicate_rows"], 0)

    def test_inspect_dataset_returns_expected_structure(self):
        content = create_valid_csv_content()
        result = inspect_dataset(content, "test.csv")

        self.assertEqual(result["filename"], "test.csv")
        self.assertEqual(result["total_rows"], 3)
        self.assertEqual(result["total_columns"], 4)
        self.assertEqual(len(result["columns"]), 4)
        self.assertIn("profile", result)

    def test_parse_empty_data_raises_validation_error(self):
        content = create_whitespace_csv_content()
        with self.assertRaises(DatasetValidationError) as ctx:
            parse_and_profile_csv(content)
        self.assertEqual(str(ctx.exception), "CSV contains no data or column headers")

    def test_parse_corrupt_csv_raises_validation_error(self):
        content = create_corrupt_csv_content()
        with self.assertRaises(DatasetValidationError) as ctx:
            parse_and_profile_csv(content)
        self.assertEqual(str(ctx.exception), "Invalid CSV format or encoding")

    def test_parse_zero_columns_raises_validation_error(self):
        # A DataFrame with 0 columns
        with patch("pandas.read_csv") as mock_read:
            import pandas as pd
            mock_read.return_value = pd.DataFrame()
            with self.assertRaises(DatasetValidationError) as ctx:
                parse_and_profile_csv(b"dummy")
            self.assertEqual(str(ctx.exception), "CSV must contain at least one column")


class TestDatasetServiceOperations(unittest.TestCase, DatasetAPITestBase):
    """Integration tests for service storage, persistence, rollback, and retrieval."""

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

    def test_create_dataset_success(self):
        csv_content = create_valid_csv_content()
        with self.TestingSessionLocal() as session:
            dataset = create_dataset(
                db=session,
                contents=csv_content,
                filename="employees.csv",
                upload_dir=self.temp_upload_dir,
                project_root=self.temp_root,
            )

            self.assertIsNotNone(dataset.id)
            self.assertEqual(dataset.filename, "employees.csv")
            self.assertEqual(dataset.total_rows, 3)
            self.assertEqual(dataset.total_columns, 4)
            self.assertEqual(dataset.storage_path, f"data/uploads/{dataset.id}.csv")

            # Verify file on disk
            stored_file = self.temp_upload_dir / f"{dataset.id}.csv"
            self.assertTrue(stored_file.exists())
            self.assertEqual(stored_file.read_bytes(), csv_content)

            # Verify record persisted in DB
            db_dataset = session.get(Dataset, dataset.id)
            self.assertIsNotNone(db_dataset)

    def test_create_dataset_external_upload_directory(self):
        csv_content = create_valid_csv_content()
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_upload = Path(outside_dir) / "external_uploads"
            with self.TestingSessionLocal() as session:
                dataset = create_dataset(
                    db=session,
                    contents=csv_content,
                    filename="external.csv",
                    upload_dir=outside_upload,
                    project_root=self.temp_root,
                )

                self.assertIsNotNone(dataset.id)
                stored_file = outside_upload / f"{dataset.id}.csv"
                self.assertTrue(stored_file.exists())
                # Should store resolved absolute path
                self.assertEqual(dataset.storage_path, str(stored_file.resolve()))

    def test_create_dataset_existing_target_file_never_overwritten_or_deleted(self):
        csv_content = create_valid_csv_content()
        fixed_id = uuid.uuid4()
        existing_file = self.temp_upload_dir / f"{fixed_id}.csv"
        original_data = b"pre_existing_unrelated_content\n"
        existing_file.write_bytes(original_data)

        with self.TestingSessionLocal() as session:
            with patch("app.services.dataset.uuid4", return_value=fixed_id):
                with self.assertRaises(DatasetStorageError) as ctx:
                    create_dataset(
                        db=session,
                        contents=csv_content,
                        filename="new_upload.csv",
                        upload_dir=self.temp_upload_dir,
                        project_root=self.temp_root,
                    )

                self.assertEqual(str(ctx.exception), "Failed to store uploaded CSV file")
                self.assertIsInstance(ctx.exception.__cause__, FileExistsError)

                # Ensure existing file was never overwritten or deleted
                self.assertTrue(existing_file.exists())
                self.assertEqual(existing_file.read_bytes(), original_data)

    def test_create_dataset_storage_error_on_os_error(self):
        csv_content = create_valid_csv_content()
        with self.TestingSessionLocal() as session:
            with patch.object(Path, "mkdir", side_effect=OSError("Directory creation failed")):
                with self.assertRaises(DatasetStorageError) as ctx:
                    create_dataset(
                        db=session,
                        contents=csv_content,
                        filename="fail.csv",
                        upload_dir=self.temp_upload_dir,
                        project_root=self.temp_root,
                    )
                self.assertIn("Failed to store uploaded CSV file", str(ctx.exception))

    def test_create_dataset_partial_file_write_failure_cleans_up(self):
        csv_content = create_valid_csv_content()

        # Create a pre-existing file in upload dir that should remain untouched
        pre_existing = self.temp_upload_dir / "pre_existing.csv"
        pre_existing.write_bytes(b"col1\nval1\n")

        import builtins
        real_open = builtins.open

        def side_effect_open(file, mode="r", *args, **kwargs):
            f = real_open(file, mode, *args, **kwargs)
            if mode == "xb":
                real_write = f.write

                def failing_write(data):
                    real_write(data[:5])
                    f.flush()
                    raise OSError("Disk full during write")

                f.write = failing_write
            return f

        with self.TestingSessionLocal() as session:
            with patch("builtins.open", side_effect=side_effect_open):
                with self.assertRaises(DatasetStorageError) as ctx:
                    create_dataset(
                        db=session,
                        contents=csv_content,
                        filename="fail_partial.csv",
                        upload_dir=self.temp_upload_dir,
                        project_root=self.temp_root,
                    )

                self.assertEqual(str(ctx.exception), "Failed to store uploaded CSV file")
                self.assertIsInstance(ctx.exception.__cause__, OSError)
                self.assertEqual(str(ctx.exception.__cause__), "Disk full during write")

                # The partial file was removed and pre-existing was untouched
                remaining_files = sorted(f.name for f in self.temp_upload_dir.glob("*.csv"))
                self.assertEqual(remaining_files, ["pre_existing.csv"])

    def test_create_dataset_partial_write_cleanup_failure_preserves_storage_error(self):
        csv_content = create_valid_csv_content()

        import builtins
        real_open = builtins.open

        def side_effect_open(file, mode="r", *args, **kwargs):
            f = real_open(file, mode, *args, **kwargs)
            if mode == "xb":
                real_write = f.write

                def failing_write(data):
                    real_write(data[:5])
                    f.flush()
                    raise OSError("Disk full during write")

                f.write = failing_write
            return f

        with self.TestingSessionLocal() as session:
            with patch("builtins.open", side_effect=side_effect_open):
                with patch.object(Path, "unlink", side_effect=OSError("Unlink failed")):
                    with self.assertRaises(DatasetStorageError) as ctx:
                        create_dataset(
                            db=session,
                            contents=csv_content,
                            filename="fail_partial.csv",
                            upload_dir=self.temp_upload_dir,
                            project_root=self.temp_root,
                        )

                    self.assertEqual(str(ctx.exception), "Failed to store uploaded CSV file")
                    self.assertIsInstance(ctx.exception.__cause__, OSError)
                    self.assertEqual(str(ctx.exception.__cause__), "Disk full during write")

    def test_create_dataset_commit_failure_combined_with_rollback_failure(self):
        csv_content = create_valid_csv_content()
        with self.TestingSessionLocal() as session:
            with patch.object(session, "commit", side_effect=SQLAlchemyError("Primary commit error")):
                with patch.object(session, "rollback", side_effect=SQLAlchemyError("Secondary rollback error")):
                    with self.assertRaises(DatasetDatabaseError) as ctx:
                        create_dataset(
                            db=session,
                            contents=csv_content,
                            filename="fail_rollback.csv",
                            upload_dir=self.temp_upload_dir,
                            project_root=self.temp_root,
                        )

                    self.assertEqual(str(ctx.exception), "Failed to save dataset metadata")
                    self.assertIsInstance(ctx.exception.__cause__, SQLAlchemyError)
                    self.assertEqual(str(ctx.exception.__cause__), "Primary commit error")

                    # Verify cleanup was still attempted and completed
                    remaining_files = list(self.temp_upload_dir.glob("*.csv"))
                    self.assertEqual(len(remaining_files), 0)

    def test_create_dataset_cleans_up_file_on_database_failure(self):
        csv_content = create_valid_csv_content()
        with self.TestingSessionLocal() as session:
            with patch.object(session, "commit", side_effect=SQLAlchemyError("DB write failed")):
                with self.assertRaises(DatasetDatabaseError) as ctx:
                    create_dataset(
                        db=session,
                        contents=csv_content,
                        filename="fail_db.csv",
                        upload_dir=self.temp_upload_dir,
                        project_root=self.temp_root,
                    )

                self.assertEqual(str(ctx.exception), "Failed to save dataset metadata")

                # Verify all files in upload dir were cleaned up
                remaining_files = list(self.temp_upload_dir.glob("*.csv"))
                self.assertEqual(len(remaining_files), 0)

    def test_create_dataset_cleanup_failure_does_not_mask_db_error(self):
        csv_content = create_valid_csv_content()
        with self.TestingSessionLocal() as session:
            with patch.object(session, "commit", side_effect=SQLAlchemyError("DB write failed")):
                with patch.object(Path, "unlink", side_effect=OSError("Unlink permission denied")):
                    with self.assertRaises(DatasetDatabaseError) as ctx:
                        create_dataset(
                            db=session,
                            contents=csv_content,
                            filename="fail_db.csv",
                            upload_dir=self.temp_upload_dir,
                            project_root=self.temp_root,
                        )

                    # Original DatasetDatabaseError is still raised
                    self.assertEqual(str(ctx.exception), "Failed to save dataset metadata")

    def test_list_and_get_dataset(self):
        csv_content = create_valid_csv_content()
        with self.TestingSessionLocal() as session:
            # Empty list
            self.assertEqual(list_datasets(session), [])

            # Get non-existent
            random_id = uuid.uuid4()
            self.assertIsNone(get_dataset(session, random_id))

            # Create 2 datasets
            d1 = create_dataset(
                db=session,
                contents=csv_content,
                filename="first.csv",
                upload_dir=self.temp_upload_dir,
                project_root=self.temp_root,
            )
            d2 = create_dataset(
                db=session,
                contents=csv_content,
                filename="second.csv",
                upload_dir=self.temp_upload_dir,
                project_root=self.temp_root,
            )

            # List datasets
            items = list_datasets(session)
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0].id, d2.id)
            self.assertEqual(items[1].id, d1.id)

            # Get dataset by id
            fetched = get_dataset(session, d1.id)
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.id, d1.id)
            self.assertEqual(fetched.filename, "first.csv")

    def test_list_datasets_raises_database_error_on_sqlalchemy_error(self):
        with self.TestingSessionLocal() as session:
            with patch.object(session, "execute", side_effect=SQLAlchemyError("DB query failed")):
                with self.assertRaises(DatasetDatabaseError) as ctx:
                    list_datasets(session)
                self.assertEqual(str(ctx.exception), "Failed to retrieve datasets")
                self.assertIsInstance(ctx.exception.__cause__, SQLAlchemyError)

    def test_get_dataset_raises_database_error_on_sqlalchemy_error(self):
        with self.TestingSessionLocal() as session:
            with patch.object(session, "get", side_effect=SQLAlchemyError("DB get failed")):
                with self.assertRaises(DatasetDatabaseError) as ctx:
                    get_dataset(session, uuid.uuid4())
                self.assertEqual(str(ctx.exception), "Failed to retrieve dataset")
                self.assertIsInstance(ctx.exception.__cause__, SQLAlchemyError)


if __name__ == "__main__":
    unittest.main()

