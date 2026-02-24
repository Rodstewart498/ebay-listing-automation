"""Tests for atomic JSON read/write with backup rotation."""

import json
import os
import pytest

from ebay_automation.atomic_io import atomic_json_write, safe_json_read


@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory for test files."""
    return str(tmp_path)


class TestAtomicJsonWrite:
    """Tests for the atomic write function."""

    def test_basic_write(self, temp_dir):
        filepath = os.path.join(temp_dir, "test.json")
        data = {"key": "value", "count": 42}
        atomic_json_write(filepath, data, create_backup=False)

        with open(filepath, 'r') as f:
            result = json.load(f)
        assert result == data

    def test_creates_parent_directories(self, temp_dir):
        filepath = os.path.join(temp_dir, "sub", "dir", "test.json")
        atomic_json_write(filepath, {"test": True}, create_backup=False)
        assert os.path.exists(filepath)

    def test_creates_backup(self, temp_dir):
        filepath = os.path.join(temp_dir, "test.json")

        # First write
        atomic_json_write(filepath, {"version": 1})

        # Second write should create .bak
        atomic_json_write(filepath, {"version": 2})

        assert os.path.exists(filepath + '.bak')
        with open(filepath + '.bak', 'r') as f:
            backup = json.load(f)
        assert backup["version"] == 1

    def test_rotates_bak_to_bak2(self, temp_dir):
        filepath = os.path.join(temp_dir, "test.json")

        atomic_json_write(filepath, {"version": 1})
        atomic_json_write(filepath, {"version": 2})
        atomic_json_write(filepath, {"version": 3})

        assert os.path.exists(filepath + '.bak2')
        with open(filepath + '.bak2', 'r') as f:
            bak2 = json.load(f)
        assert bak2["version"] == 1

    def test_overwrites_existing_file(self, temp_dir):
        filepath = os.path.join(temp_dir, "test.json")
        atomic_json_write(filepath, {"old": True}, create_backup=False)
        atomic_json_write(filepath, {"new": True}, create_backup=False)

        with open(filepath, 'r') as f:
            result = json.load(f)
        assert result == {"new": True}

    def test_handles_unicode(self, temp_dir):
        filepath = os.path.join(temp_dir, "test.json")
        data = {"emoji": "🔧", "accent": "café"}
        atomic_json_write(filepath, data, ensure_ascii=False, create_backup=False)

        with open(filepath, 'r', encoding='utf-8') as f:
            result = json.load(f)
        assert result["emoji"] == "🔧"

    def test_handles_large_data(self, temp_dir):
        filepath = os.path.join(temp_dir, "test.json")
        data = [{"id": i, "value": f"item_{i}"} for i in range(10000)]
        atomic_json_write(filepath, data, create_backup=False)

        with open(filepath, 'r') as f:
            result = json.load(f)
        assert len(result) == 10000

    def test_no_partial_writes(self, temp_dir):
        """Verify no temp files are left behind on success."""
        filepath = os.path.join(temp_dir, "test.json")
        atomic_json_write(filepath, {"clean": True}, create_backup=False)

        tmp_files = [f for f in os.listdir(temp_dir) if f.endswith('.tmp')]
        assert len(tmp_files) == 0


class TestSafeJsonRead:
    """Tests for the safe read function with backup fallback."""

    def test_reads_primary(self, temp_dir):
        filepath = os.path.join(temp_dir, "test.json")
        with open(filepath, 'w') as f:
            json.dump({"source": "primary"}, f)

        result = safe_json_read(filepath)
        assert result["source"] == "primary"

    def test_falls_back_to_bak(self, temp_dir):
        filepath = os.path.join(temp_dir, "test.json")
        # No primary file, but .bak exists
        with open(filepath + '.bak', 'w') as f:
            json.dump({"source": "backup"}, f)

        result = safe_json_read(filepath)
        assert result["source"] == "backup"

    def test_falls_back_to_bak2(self, temp_dir):
        filepath = os.path.join(temp_dir, "test.json")
        # Only .bak2 exists
        with open(filepath + '.bak2', 'w') as f:
            json.dump({"source": "backup2"}, f)

        result = safe_json_read(filepath)
        assert result["source"] == "backup2"

    def test_returns_default_when_all_missing(self, temp_dir):
        filepath = os.path.join(temp_dir, "nonexistent.json")
        result = safe_json_read(filepath, default={"fallback": True})
        assert result == {"fallback": True}

    def test_skips_corrupted_primary(self, temp_dir):
        filepath = os.path.join(temp_dir, "test.json")
        with open(filepath, 'w') as f:
            f.write("NOT VALID JSON {{{")
        with open(filepath + '.bak', 'w') as f:
            json.dump({"source": "backup"}, f)

        result = safe_json_read(filepath)
        assert result["source"] == "backup"

    def test_default_is_none(self, temp_dir):
        filepath = os.path.join(temp_dir, "nonexistent.json")
        result = safe_json_read(filepath)
        assert result is None
