import pytest
import tempfile
import os
from pathlib import Path


@pytest.fixture
def temp_repo(tmp_path):
    os.system(f"git init {tmp_path} --quiet")
    return tmp_path


@pytest.fixture
def temp_file(tmp_path):
    file_path = tmp_path / "test.txt"
    file_path.write_text("hello world")
    return file_path
