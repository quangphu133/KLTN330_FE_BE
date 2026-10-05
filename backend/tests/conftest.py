import os
import tempfile
import uuid
from pathlib import Path


test_database = Path(tempfile.gettempdir()) / f"kltn330_backend_tests_{uuid.uuid4().hex}.sqlite3"
isolated_database_url = os.environ.get("KLTN_TEST_DATABASE_URL")
if isolated_database_url:
    if "test" not in isolated_database_url.rsplit("/", 1)[-1].lower():
        raise ValueError("KLTN_TEST_DATABASE_URL must point to a database whose name includes 'test'")
    os.environ["DATABASE_URL"] = isolated_database_url
else:
    os.environ["DATABASE_URL"] = f"sqlite:///{test_database.as_posix()}"

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings

settings.UPLOAD_DIR = Path(tempfile.gettempdir()) / f"kltn330_backend_uploads_{uuid.uuid4().hex}"
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

import pytest


@pytest.fixture(scope="session", autouse=True)
def initialize_test_database():
    from app.db.init_db import initialize_database

    initialize_database()
