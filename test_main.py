#!/usr/bin/env python3
"""Unit tests for sort-tier.py file organization utility."""

import os
import sys
import pytest
import tempfile
import logging
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, mock_open
from datetime import datetime, timedelta
import hashlib

from main import (
    is_system_file,
    month_key_from_ctime,
    choose_directory_gui,
    choose_directory_console,
    choose_directory,
    ensure_unique_dest,
    setup_logger,
    file_sha256,
    decide_destination,
    send_to_trash,
    safe_move,
    safe_copy,
    safe_copy_only,
    safe_copy_and_trash,
    collect_files,
    organize,
    ALLOWED_EXTS,
    IMAGE_EXTS,
    DOC_EXTS,
    VIDEO_EXTS,
    INSTALLER_EXTS,
)


class TestFileClassification:
    """Tests for file classification and filtering."""

    def system_file_returns_false_for_non_system_files(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        assert is_system_file(test_file) is False

    def month_key_returns_correct_format_for_valid_file(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        result = month_key_from_ctime(test_file)
        assert result.count('-') == 1
        assert len(result) == 7
        year, month = result.split('-')
        assert 1900 <= int(year) <= 2100
        assert 1 <= int(month) <= 12

    def month_key_returns_unknown_for_inaccessible_file(self):
        non_existent = Path("/non/existent/path/file.txt")
        assert month_key_from_ctime(non_existent) == "unknown"


class TestDirectorySelection:
    """Tests for directory selection operations."""

    def choose_directory_gui_returns_none_when_tkinter_unavailable(self):
        with patch('main._TK_AVAILABLE', False):
            assert choose_directory_gui("prompt") is None

    def choose_directory_gui_returns_path_when_selected(self):
        with patch('main._TK_AVAILABLE', True):
            with patch('main.tk.Tk') as mock_tk:
                mock_instance = MagicMock()
                mock_tk.return_value = mock_instance
                with patch('main.filedialog.askdirectory', return_value="/test/path"):
                    result = choose_directory_gui("prompt")
                    assert result == Path("/test/path")

    def choose_directory_gui_returns_none_when_cancelled(self):
        with patch('main._TK_AVAILABLE', True):
            with patch('main.tk.Tk') as mock_tk:
                mock_instance = MagicMock()
                mock_tk.return_value = mock_instance
                with patch('main.filedialog.askdirectory', return_value=""):
                    result = choose_directory_gui("prompt")
                    assert result is None

    def choose_directory_console_returns_path_for_valid_input(self):
        with patch('builtins.input', return_value="/test/path"):
            result = choose_directory_console()
            assert result == Path("/test/path")

    def choose_directory_console_returns_none_for_empty_input(self):
        with patch('builtins.input', return_value=""):
            result = choose_directory_console()
            assert result is None

    def choose_directory_console_returns_none_for_eof(self):
        with patch('builtins.input', side_effect=EOFError):
            result = choose_directory_console()
            assert result is None

    def choose_directory_falls_back_to_console_when_gui_unavailable(self):
        with patch('main.choose_directory_gui', return_value=None):
            with patch('builtins.input', return_value="/console/path"):
                with patch('builtins.print'):
                    result = choose_directory("/console/path")
                    assert result == Path("/console/path")

    def choose_directory_uses_gui_when_available(self):
        gui_path = Path("/gui/path")
        with patch('main.choose_directory_gui', return_value=gui_path):
            result = choose_directory("prompt")
            assert result == gui_path


class TestFileDestination:
    """Tests for file destination handling."""

    def ensure_unique_dest_returns_same_path_when_not_exists(self, tmp_path):
        dest = tmp_path / "new_file.txt"
        result = ensure_unique_dest(dest)
        assert result == dest

    def ensure_unique_dest_appends_suffix_when_exists(self, tmp_path):
        dest = tmp_path / "file.txt"
        dest.write_text("content")
        result = ensure_unique_dest(dest)
        assert result == tmp_path / "file_1.txt"

    def ensure_unique_dest_increments_suffix_for_multiple_existing(self, tmp_path):
        dest = tmp_path / "file.txt"
        dest.write_text("content")
        (tmp_path / "file_1.txt").write_text("content")
        result = ensure_unique_dest(dest)
        assert result == tmp_path / "file_2.txt"

    def ensure_unique_dest_preserves_file_extension(self, tmp_path):
        dest = tmp_path / "file.pdf"
        dest.write_text("content")
        result = ensure_unique_dest(dest)
        assert result.suffix == ".pdf"


class TestFileHashing:
    """Tests for SHA256 file hashing."""

    def file_sha256_returns_correct_hash_for_valid_file(self, tmp_path):
        test_file = tmp_path / "test.txt"
        content = "test content"
        test_file.write_text(content)
        expected_hash = hashlib.sha256(content.encode()).hexdigest()
        result = file_sha256(test_file)
        assert result == expected_hash

    def file_sha256_returns_empty_string_for_nonexistent_file(self):
        non_existent = Path("/non/existent/file.txt")
        result = file_sha256(non_existent)
        assert result == ""

    def file_sha256_returns_same_hash_for_identical_files(self, tmp_path):
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        content = "identical content"
        file1.write_text(content)
        file2.write_text(content)
        hash1 = file_sha256(file1)
        hash2 = file_sha256(file2)
        assert hash1 == hash2

    def file_sha256_returns_different_hashes_for_different_files(self, tmp_path):
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")
        hash1 = file_sha256(file1)
        hash2 = file_sha256(file2)
        assert hash1 != hash2


class TestDestinationDecision:
    """Tests for destination path decision logic."""

    def decide_destination_returns_path_and_no_overwrite_when_not_exists(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("content")
        desired = tmp_path / "dest.txt"
        chosen, overwrite = decide_destination(src, desired)
        assert chosen == desired
        assert overwrite is False

    def decide_destination_returns_path_and_overwrite_when_identical(self, tmp_path):
        content = "identical"
        src = tmp_path / "source.txt"
        desired = tmp_path / "dest.txt"
        src.write_text(content)
        desired.write_text(content)
        chosen, overwrite = decide_destination(src, desired)
        assert chosen == desired
        assert overwrite is True

    def decide_destination_returns_unique_path_when_different(self, tmp_path):
        src = tmp_path / "source.txt"
        desired = tmp_path / "dest.txt"
        src.write_text("content1")
        desired.write_text("content2")
        chosen, overwrite = decide_destination(src, desired)
        assert chosen != desired
        assert overwrite is False
        assert "_1" in str(chosen)


class TestFileOperations:
    """Tests for file move and copy operations."""

    def safe_move_logs_operation_in_dry_run(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("content")
        dest = tmp_path / "dest.txt"
        logger = Mock()
        safe_move(src, dest, dry_run=True, logger=logger)
        logger.info.assert_called()
        call_args = logger.info.call_args[0][0]
        assert "[DRY-RUN]" in call_args and "Move" in call_args

    def safe_move_moves_file_when_not_dry_run(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("content")
        dest = tmp_path / "subdir" / "dest.txt"
        logger = Mock()
        safe_move(src, dest, dry_run=False, logger=logger)
        assert not src.exists()
        assert dest.exists()
        assert dest.read_text() == "content"

    def safe_move_overwrites_identical_file(self, tmp_path):
        content = "identical"
        src = tmp_path / "source.txt"
        dest = tmp_path / "dest.txt"
        src.write_text(content)
        dest.write_text(content)
        logger = Mock()
        safe_move(src, dest, dry_run=False, logger=logger)
        assert not src.exists()
        assert dest.exists()

    def safe_copy_logs_operation_in_dry_run(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("content")
        dest = tmp_path / "dest.txt"
        logger = Mock()
        safe_copy(src, dest, dry_run=True, logger=logger)
        logger.info.assert_called()
        call_args = logger.info.call_args[0][0]
        assert "[DRY-RUN]" in call_args and "Copy" in call_args

    def safe_copy_copies_file_preserving_metadata(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("content")
        dest = tmp_path / "subdir" / "dest.txt"
        logger = Mock()
        safe_copy(src, dest, dry_run=False, logger=logger)
        assert src.exists()
        assert dest.exists()
        assert dest.read_text() == "content"

    def safe_copy_only_copies_without_moving(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("content")
        dest = tmp_path / "dest.txt"
        logger = Mock()
        result = safe_copy_only(src, dest, dry_run=False, logger=logger)
        assert src.exists()
        assert dest.exists()

    def safe_copy_and_trash_copies_and_removes_original_in_non_dry_run(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("content")
        dest = tmp_path / "dest.txt"
        trash_dir = tmp_path / "trash"
        logger = Mock()
        with patch('main._SEND2TRASH_AVAILABLE', False):
            safe_copy_and_trash(src, dest, dry_run=False, logger=logger, fallback_trash_dir=trash_dir)
        assert dest.exists()
        assert not src.exists()

    def safe_copy_and_trash_logs_operations_in_dry_run(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("content")
        dest = tmp_path / "dest.txt"
        logger = Mock()
        safe_copy_and_trash(src, dest, dry_run=True, logger=logger)
        logger.info.assert_called()


class TestTrashOperations:
    """Tests for file trash operations."""

    def send_to_trash_logs_dry_run_operation(self, tmp_path):
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")
        logger = Mock()
        send_to_trash(file_path, dry_run=True, logger=logger)
        logger.info.assert_called()
        assert file_path.exists()

    def send_to_trash_uses_fallback_when_send2trash_unavailable(self, tmp_path):
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")
        trash_dir = tmp_path / "Trash"
        logger = Mock()
        with patch('main._SEND2TRASH_AVAILABLE', False):
            result = send_to_trash(file_path, dry_run=False, logger=logger, fallback_trash_dir=trash_dir)
        assert result is True
        assert not file_path.exists()
        assert trash_dir.exists()

    def send_to_trash_returns_false_when_no_fallback_provided(self, tmp_path):
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")
        logger = Mock()
        with patch('main._SEND2TRASH_AVAILABLE', False):
            result = send_to_trash(file_path, dry_run=False, logger=logger)
        assert result is False

    def send_to_trash_attempts_send2trash_when_available(self, tmp_path):
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")
        logger = Mock()
        with patch('main._SEND2TRASH_AVAILABLE', True):
            with patch('main.send2trash') as mock_send2trash:
                result = send_to_trash(file_path, dry_run=False, logger=logger)
        assert result is True


class TestFileCollection:
    """Tests for file collection and filtering."""

    def collect_files_returns_empty_list_for_empty_directory(self, tmp_path):
        result = collect_files(tmp_path, allowed_exts=ALLOWED_EXTS)
        assert result == []

    def collect_files_returns_all_allowed_files(self, tmp_path):
        (tmp_path / "image.jpg").write_text("content")
        (tmp_path / "document.pdf").write_text("content")
        result = collect_files(tmp_path, allowed_exts=ALLOWED_EXTS)
        assert len(result) == 2

    def collect_files_filters_non_allowed_extensions(self, tmp_path):
        (tmp_path / "image.jpg").write_text("content")
        (tmp_path / "unknown.xyz").write_text("content")
        result = collect_files(tmp_path, allowed_exts=ALLOWED_EXTS)
        assert len(result) == 1
        assert result[0].suffix.lower() == ".jpg"

    def collect_files_recursively_scans_subdirectories(self, tmp_path):
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (tmp_path / "image1.jpg").write_text("content")
        (subdir / "image2.jpg").write_text("content")
        result = collect_files(tmp_path, allowed_exts=ALLOWED_EXTS)
        assert len(result) == 2

    def collect_files_excludes_specified_directories(self, tmp_path):
        exclude_dir = tmp_path / "exclude"
        exclude_dir.mkdir()
        (tmp_path / "image.jpg").write_text("content")
        (exclude_dir / "image.jpg").write_text("content")
        result = collect_files(tmp_path, exclude_dirs=[exclude_dir], allowed_exts=ALLOWED_EXTS)
        assert len(result) == 1

    def collect_files_only_returns_files_not_directories(self, tmp_path):
        (tmp_path / "subdir").mkdir()
        (tmp_path / "file.jpg").write_text("content")
        result = collect_files(tmp_path, allowed_exts=ALLOWED_EXTS)
        assert len(result) == 1
        assert result[0].is_file()


class TestLogging:
    """Tests for logging setup and operations."""

    def setup_logger_creates_log_file(self, tmp_path):
        log_file = tmp_path / "test.log"
        logger = setup_logger(log_file)
        logger.info("test message")
        assert log_file.exists()

    def setup_logger_writes_messages_to_file(self, tmp_path):
        log_file = tmp_path / "test.log"
        logger = setup_logger(log_file)
        logger.info("test message")
        content = log_file.read_text()
        assert "test message" in content

    def setup_logger_uses_utf8_encoding(self, tmp_path):
        log_file = tmp_path / "test.log"
        logger = setup_logger(log_file)
        logger.info("тестовое сообщение")
        content = log_file.read_text(encoding='utf-8')
        assert "тестовое сообщение" in content

    def setup_logger_formats_with_timestamp_and_level(self, tmp_path):
        log_file = tmp_path / "test.log"
        logger = setup_logger(log_file)
        logger.info("test")
        content = log_file.read_text()
        assert "INFO" in content


class TestOrganizeFunction:
    """Tests for main organize function."""

    def organize_creates_month_directories(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        (source / "file.jpg").write_text("content")
        organize(source, target, ALLOWED_EXTS, dry_run=False)
        month_dirs = list(target.glob("20*-*"))
        assert len(month_dirs) > 0

    def organize_groups_files_by_month(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        (source / "image.jpg").write_text("content")
        (source / "doc.pdf").write_text("content")
        organize(source, target, ALLOWED_EXTS, dry_run=False)
        log_file = target / "organizer.log"
        assert log_file.exists()

    def organize_creates_extension_subdirectories(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        (source / "file1.jpg").write_text("content1")
        (source / "file2.jpg").write_text("content2")
        organize(source, target, ALLOWED_EXTS, dry_run=False)
        jpg_dirs = list(target.glob("**/jpg"))
        assert len(jpg_dirs) > 0

    def organize_creates_singles_directory_for_unique_extensions(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        (source / "only_file.jpg").write_text("content")
        organize(source, target, ALLOWED_EXTS, dry_run=False)
        singles = list(target.glob("**/Singles"))
        assert len(singles) > 0

    def organize_logs_all_operations(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        (source / "file.jpg").write_text("content")
        organize(source, target, ALLOWED_EXTS, dry_run=False)
        log_file = target / "organizer.log"
        content = log_file.read_text()
        assert "Start organizing" in content
        assert "Organizing finished" in content

    def organize_does_not_modify_files_in_dry_run(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        file_path = source / "file.jpg"
        file_path.write_text("content")
        organize(source, target, ALLOWED_EXTS, dry_run=True)
        assert file_path.exists()
        assert len(list(target.glob("**/jpg"))) == 0

    def organize_copies_installers_instead_of_moving(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        installer = source / "setup.exe"
        installer.write_text("content")
        organize(source, target, ALLOWED_EXTS, dry_run=False)
        assert installer.exists()

    def organize_uses_copy_and_trash_mode_when_enabled(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        (source / "file.jpg").write_text("content")
        with patch('main._SEND2TRASH_AVAILABLE', False):
            organize(source, target, ALLOWED_EXTS, dry_run=False, copy_and_trash=True)
        assert not (source / "file.jpg").exists()

