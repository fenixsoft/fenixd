"""
tests/test_supervisor_log_single_write.py — fix-observability-gaps 4.3

验证 supervisor.log() 双写修正：
- stdout 重定向到同一日志文件时，log() 只写一次（文件为唯一 sink）
- stdout 未重定向时，log() 既 print 又写文件（双 sink，控制台可见性）
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# 模块级导入 supervisor（conftest 同款）
import bin.fenixd_supervisor as supervisor_mod


class TestSupervisorLogSingleWrite:
    def test_stdout_redirected_to_log_file_single_write(self, tmp_path, monkeypatch):
        """stdout 重定向到 LOG_FILE → log() 每条消息只出现一次（4.2 修正）。"""
        # 构造临时日志文件
        log_path = tmp_path / "logs" / "supervisor.log"
        log_path.parent.mkdir(parents=True)
        monkeypatch.setattr(supervisor_mod, "LOG_FILE", log_path)

        # 模拟 stdout 重定向到同一文件（模拟 `>> supervisor.log 2>&1`）
        fd_out = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        saved_stdout = os.dup(sys.stdout.fileno())
        os.dup2(fd_out, sys.stdout.fileno())
        os.close(fd_out)

        try:
            supervisor_mod.log("test-single-write-message-AAA")
        finally:
            os.dup2(saved_stdout, sys.stdout.fileno())
            os.close(saved_stdout)

        # 关闭 stdout 的 fd 写缓冲（确保写入落盘）
        try:
            sys.stdout.flush()
        except Exception:
            pass

        content = log_path.read_text(encoding="utf-8")
        assert "test-single-write-message-AAA" in content
        # 单次调用只应出现一次（双写会两次）
        assert content.count("test-single-write-message-AAA") == 1, \
            f"log() 双写未修正：{content.count('test-single-write-message-AAA')} 次出现"

    def test_stdout_not_redirected_to_log(self, tmp_path, capsys, monkeypatch):
        """stdout 未重定向到 LOG_FILE → log() 既写文件又 print（控制台可见性）。"""
        log_path = tmp_path / "logs" / "supervisor.log"
        log_path.parent.mkdir(parents=True)
        monkeypatch.setattr(supervisor_mod, "LOG_FILE", log_path)

        supervisor_mod.log("test-console-visible-XXX")

        # 文件中应有消息
        content = log_path.read_text(encoding="utf-8")
        assert "test-console-visible-XXX" in content

        # capsys 捕获的 stdout 也应有消息（控制台可见性保留）
        captured = capsys.readouterr()
        assert "test-console-visible-XXX" in captured.out

    def test_stdout_points_to_log_file_identifies_same_file(self, tmp_path, monkeypatch):
        """_stdout_points_to_log_file 在 stdout 指向 LOG_FILE 时返回 True。"""
        log_path = tmp_path / "logs" / "test_supervisor.log"
        log_path.parent.mkdir(parents=True)
        monkeypatch.setattr(supervisor_mod, "LOG_FILE", log_path)

        fd_out = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        saved_stdout = os.dup(sys.stdout.fileno())
        os.dup2(fd_out, sys.stdout.fileno())
        os.close(fd_out)

        try:
            assert supervisor_mod._stdout_points_to_log_file() is True
        finally:
            os.dup2(saved_stdout, sys.stdout.fileno())
            os.close(saved_stdout)

    def test_stdout_points_to_log_file_false_for_different_file(self, tmp_path, monkeypatch):
        """stdout 指向不同文件时 _stdout_points_to_log_file 返回 False。"""
        log_path = tmp_path / "logs" / "different_file.log"
        log_path.parent.mkdir(parents=True)
        monkeypatch.setattr(supervisor_mod, "LOG_FILE", log_path)

        # 默认 stdout 未被重定向
        assert supervisor_mod._stdout_points_to_log_file() is False
