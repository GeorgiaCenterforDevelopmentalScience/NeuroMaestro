import os
import tempfile
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from neuromaestro.pipeline.utils.detect_subjects import (
    detect_subjects,
    parse_subjects_input,
    save_subjects_to_file,
)


class TestParseSubjectsInput:

    def test_comma_separated_string(self):
        assert parse_subjects_input("001,002,003") == ["001", "002", "003"]

    def test_comma_separated_with_spaces(self):
        assert parse_subjects_input("001, 002 , 003") == ["001", "002", "003"]

    def test_newline_separated_file(self, tmp_path):
        f = tmp_path / "subjects.txt"
        f.write_text("001\n002\n003")
        assert parse_subjects_input(str(f)) == ["001", "002", "003"]

    def test_comma_separated_file(self, tmp_path):
        f = tmp_path / "subjects.txt"
        f.write_text("001,002,003")
        assert parse_subjects_input(str(f)) == ["001", "002", "003"]

    def test_file_with_trailing_newline(self, tmp_path):
        f = tmp_path / "subjects.txt"
        f.write_text("001\n002\n003\n")
        assert parse_subjects_input(str(f)) == ["001", "002", "003"]

    def test_empty_string(self):
        assert parse_subjects_input("") == []

    def test_skips_blank_entries(self):
        assert parse_subjects_input("001,,003") == ["001", "003"]


class TestDetectSubjects:

    def test_detects_sub_prefix(self, tmp_path):
        (tmp_path / "sub-001").mkdir()
        (tmp_path / "sub-002").mkdir()
        (tmp_path / "not_a_subject").mkdir()
        assert detect_subjects(str(tmp_path)) == ["001", "002"]

    def test_custom_prefix(self, tmp_path):
        (tmp_path / "s001").mkdir()
        (tmp_path / "s002").mkdir()
        assert detect_subjects(str(tmp_path), prefix="s") == ["001", "002"]

    def test_ignores_files(self, tmp_path):
        (tmp_path / "sub-001").mkdir()
        (tmp_path / "sub-002.txt").write_text("")
        assert detect_subjects(str(tmp_path)) == ["001"]

    def test_empty_directory(self, tmp_path):
        assert detect_subjects(str(tmp_path)) == []

    def test_nonexistent_directory(self, tmp_path):
        assert detect_subjects(str(tmp_path / "missing")) == []


class TestSaveSubjectsToFile:

    def test_writes_comma_separated(self, tmp_path):
        f = tmp_path / "out.txt"
        save_subjects_to_file(["001", "002", "003"], str(f))
        assert f.read_text() == "001,002,003"

    def test_creates_parent_dirs(self, tmp_path):
        f = tmp_path / "subdir" / "out.txt"
        save_subjects_to_file(["001"], str(f))
        assert f.exists()

    def test_empty_list_writes_empty_file(self, tmp_path):
        f = tmp_path / "out.txt"
        save_subjects_to_file([], str(f))
        assert f.read_text() == ""
