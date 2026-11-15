import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database import DATABASE_URL, Base, get_db
from app.main import app as fastapi_app
import app.datasets
from app.models import Dataset


def _normalize_host(host: str | None) -> str:
    """Normalize local host variations."""
    h = (host or "localhost").lower().strip()
    return "localhost" if h in ("127.0.0.1", "localhost", "::1") else h


def get_test_database_url() -> str:
    """
    Read and validate the TEST_DATABASE_URL directly from the environment.

    Ensures:
    1. Reads strictly from os.environ without calling load_dotenv() or falling back to dev DB.
    2. Parses and compares normalized database identity using SQLAlchemy make_url().
    3. Rejects the development database even if URL formatting differs.
    4. Requires the test database name to end in '_test'.
    5. Never exposes database credentials in error messages.
    """
    test_db_url = os.environ.get("TEST_DATABASE_URL")
    if not test_db_url or not test_db_url.strip():
        raise RuntimeError(
            "TEST_DATABASE_URL environment variable is not configured. "
            "Please configure an isolated PostgreSQL test database ending in '_test'."
        )

    test_db_url = test_db_url.strip()

    try:
        parsed_test_url = make_url(test_db_url)
    except Exception:
        raise RuntimeError(
            "TEST_DATABASE_URL is not a valid database URL format."
        ) from None

    # 1. Require test database name to end in '_test'
    test_db_name = (parsed_test_url.database or "").strip()
    if not test_db_name or not test_db_name.endswith("_test"):
        raise RuntimeError(
            "Test database name must end in '_test' to ensure test isolation."
        )

    # 2. Normalize and compare with development database identity
    try:
        parsed_dev_url = make_url(DATABASE_URL)
    except Exception:
        raise RuntimeError(
            "Application development database URL cannot be parsed for safety verification."
        ) from None

    test_host = _normalize_host(parsed_test_url.host)
    dev_host = _normalize_host(parsed_dev_url.host)
    test_port = parsed_test_url.port or 5432
    dev_port = parsed_dev_url.port or 5432
    dev_db_name = (parsed_dev_url.database or "").strip()

    # Reject matching host + port + database, even if usernames differ, for conservative protection
    if (test_host, test_port, test_db_name) == (dev_host, dev_port, dev_db_name):
        raise RuntimeError(
            "TEST_DATABASE_URL points to the application's development database. "
            "Please configure an isolated PostgreSQL test database."
        )

    return test_db_url


def create_valid_csv_content() -> bytes:
    """Return bytes of a valid, realistic CSV file."""
    return (
        b"name,age,salary,city\n"
        b"Alice,30,70000,Pune\n"
        b"Bob,25,50000,Mumbai\n"
        b"Charlie,35,90000,Delhi\n"
    )


def create_empty_csv_content() -> bytes:
    """Return bytes of an empty file."""
    return b""


def create_whitespace_csv_content() -> bytes:
    """Return bytes containing only whitespace/newlines."""
    return b"   \n\n\r\n   \t  \n"


def create_corrupt_csv_content() -> bytes:
    """Return bytes that fail CSV parsing or text decoding."""
    return b"\x80\x81\xfe\xff,invalid_data\n1,2,3,4,5\nonly_one_col\n"


def create_large_csv_content(size_bytes: int = (10 * 1024 * 1024 + 1024)) -> bytes:
    """Return CSV bytes exceeding the specified size (defaults to > 10 MB)."""
    header = b"col1,col2,col3,col4\n"
    line = b"1234567890,abcdefghij,1234567890,abcdefghij\n"  # 45 bytes
    repeat_count = (size_bytes // len(line)) + 1
    return header + (line * repeat_count)


class DatasetAPITestBase:
    """
    Shared test fixture setup for Dataset API integration tests.
    Sets up an isolated test database, dependency overrides,
    and a temporary upload directory.
    """

    engine = None
    TestingSessionLocal = None
    client = None
    _saved_dependency_overrides = None

    @classmethod
    def init_test_database(cls):
        test_db_url = get_test_database_url()
        cls.engine = create_engine(test_db_url, pool_pre_ping=True)
        Base.metadata.create_all(bind=cls.engine)
        cls.TestingSessionLocal = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            autocommit=False
        )

        def override_get_db():
            db = cls.TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        # Save existing dependency overrides before installing test override
        cls._saved_dependency_overrides = dict(fastapi_app.dependency_overrides)
        fastapi_app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(fastapi_app, raise_server_exceptions=False)

    @classmethod
    def teardown_test_database(cls):
        # Restore the original dependency overrides mapping without calling .clear()
        if cls._saved_dependency_overrides is not None:
            for key in list(fastapi_app.dependency_overrides.keys()):
                if key not in cls._saved_dependency_overrides:
                    del fastapi_app.dependency_overrides[key]
            for key, val in cls._saved_dependency_overrides.items():
                fastapi_app.dependency_overrides[key] = val
            cls._saved_dependency_overrides = None

        if cls.engine is not None:
            cls.engine.dispose()
            cls.engine = None

    def setup_temp_storage_and_db(self):
        # 1. Reset test database tables before each test
        self.clean_database()

        # 2. Isolate uploads to a temporary directory
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temp_dir.name)
        self.temp_upload_dir = self.temp_root / "data" / "uploads"
        self.temp_upload_dir.mkdir(parents=True, exist_ok=True)

        self.patcher_upload = patch.object(app.datasets, "UPLOAD_DIR", self.temp_upload_dir)
        self.patcher_root = patch.object(app.datasets, "PROJECT_ROOT", self.temp_root)
        self.patcher_upload.start()
        self.patcher_root.start()

    def teardown_temp_storage_and_db(self):
        # 1. Stop patches
        if hasattr(self, "patcher_upload"):
            try:
                self.patcher_upload.stop()
            except RuntimeError:
                pass
        if hasattr(self, "patcher_root"):
            try:
                self.patcher_root.stop()
            except RuntimeError:
                pass

        # 2. Clean temporary directory
        if hasattr(self, "temp_dir"):
            self.temp_dir.cleanup()

        # 3. Clean test database tables
        self.clean_database()

    def clean_database(self):
        if self.engine is not None:
            with self.engine.begin() as conn:
                conn.execute(text("TRUNCATE TABLE datasets CASCADE;"))

    def count_datasets_in_db(self) -> int:
        with self.TestingSessionLocal() as session:
            count = session.scalar(select(func.count()).select_from(Dataset))
            return count or 0

    def count_files_in_upload_dir(self) -> int:
        if not hasattr(self, "temp_upload_dir") or not self.temp_upload_dir.exists():
            return 0
        return len([f for f in self.temp_upload_dir.iterdir() if f.is_file()])

    def create_persisted_dataset(
        self,
        filename: str = "persisted.csv",
        total_rows: int = 3,
        total_columns: int = 2,
        columns: list = None,
        profile: dict = None,
        dataset_id: uuid.UUID = None,
        storage_path: str = None
    ) -> Dataset:
        if dataset_id is None:
            dataset_id = uuid.uuid4()
        if columns is None:
            columns = [
                {"name": "col1", "data_type": "int64"},
                {"name": "col2", "data_type": "object"}
            ]
        if profile is None:
            profile = {
                "total_rows": total_rows,
                "total_columns": total_columns,
                "total_missing_values": 0,
                "duplicate_rows": 0,
                "columns": [
                    {
                        "name": "col1",
                        "data_type": "int64",
                        "missing_values": 0,
                        "unique_values": total_rows,
                        "statistics": {"count": total_rows, "min": 1, "max": total_rows}
                    },
                    {
                        "name": "col2",
                        "data_type": "object",
                        "missing_values": 0,
                        "unique_values": total_rows,
                        "statistics": {}
                    }
                ]
            }
        if storage_path is None:
            storage_path = f"data/uploads/{dataset_id}.csv"

        dataset = Dataset(
            id=dataset_id,
            filename=filename,
            storage_path=storage_path,
            total_rows=total_rows,
            total_columns=total_columns,
            columns=columns,
            profile=profile
        )

        with self.TestingSessionLocal() as session:
            session.add(dataset)
            session.commit()
            session.refresh(dataset)
            session.expunge(dataset)

        return dataset
