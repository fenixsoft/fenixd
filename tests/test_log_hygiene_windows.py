"""日志卫生三件回归（fix-spawn-attribution-hardening 任务 1.4，覆盖 5.1/5.2/5.3）。

- 5.1（A5）：用户配置空对象按空配置兜底降级 debug——fresh install 合法
  初装态不污染 ERROR 告警面；
- 5.2（A6）：kill_process_group getpgid 平台守卫——win32 无 os.getpgid
  不再 AttributeError，控制台组 id＝组长 pid 直取，Linux 分支逐位不变；
- 5.3（A6）：dashboard 客户端断连静音——ConnectionReset/Aborted/
  BrokenPipe 在 handle_one_request 边界 debug 单行，非断连族异常不吞。
"""

import logging
import unittest.mock as mock
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

import core.proc_utils as proc_utils
from core.config import ConfigLoader
from core.platform import api as pal
from core.proc_utils import kill_process_group


# ── 5.1 配置空对象降级 debug ─────────────────────────────────────────


class TestConfigEmptyObjectDebug:
    """配置顶层非对象按空配置兜底（A5：fresh install 合法初装态）。"""

    @pytest.mark.parametrize("body,desc", [
        ("", "空文件（safe_load→None）"),
        ("\n", "纯空白（safe_load→None）"),
        ("- a\n- b\n", "列表顶层"),
    ])
    def test_non_dict_top_level_logs_at_most_info(self, tmp_path, caplog, body, desc):
        p = tmp_path / "config.yaml"
        p.write_text(body, encoding="utf-8")
        with caplog.at_level(logging.DEBUG, logger="fenixd.config"):
            raw = ConfigLoader._load_optional_yaml(p, "user")
        assert raw == {}
        records = [r for r in caplog.records if "顶层不是对象" in r.getMessage()]
        assert records, f"{desc} 应留 debug 单行留痕"
        assert max(r.levelno for r in records) <= logging.INFO, (
            "空对象兜底 MUST NOT 以 ERROR 级落日志（A5：初装态合法）")

    def test_valid_dict_still_loaded(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("a: 1\n", encoding="utf-8")
        assert ConfigLoader._load_optional_yaml(p, "user") == {"a": 1}


# ── 5.2 kill_process_group getpgid 平台守卫 ──────────────────────────


class _FakePopen:
    """最小 Popen 替身（kill_process_group 只触 pid/poll/wait）。"""

    def __init__(self, pid=4242, poll_result=None):
        self.pid = pid
        self.poll = mock.Mock(return_value=poll_result)
        self.wait = mock.Mock(return_value=0)


class _OsWithoutGetpgid:
    """模拟 win32 os 命名空间：无 getpgid 属性（守卫 else 分支触发面）。"""


class TestKillProcessGroupWindowsGuard:
    """win32 无 os.getpgid：直取组长 pid 为组句柄，击杀链经 pal.kill_tree。"""

    def test_win32_branch_runs_kill_chain_without_getpgid(self):
        sigs = []
        popen = _FakePopen(pid=4242)
        with mock.patch.object(proc_utils, "os", _OsWithoutGetpgid()), \
            mock.patch.object(pal, "IS_WINDOWS", True), \
            mock.patch.object(pal, "stdin_eof", return_value=True) as m_eof, \
            mock.patch.object(pal, "kill_tree",
                              side_effect=lambda pid, sig, **kw:
                              (sigs.append((pid, sig)), True)[1]):
            kill_process_group(popen, caller="test")
        # W9 第一跳 EOF 优雅层在击杀序列开始前
        m_eof.assert_called_once_with(popen)
        # 组句柄＝组长 pid（win32 控制台进程组语义），SIGTERM→wait→SIGKILL 序不变
        assert sigs == [(4242, pal.SIGTERM), (4242, pal.SIGKILL)]
        popen.wait.assert_called_once()

    def test_win32_sigterm_only_if_alive_leader_exited_skips_term(self):
        sigs = []
        popen = _FakePopen(pid=7, poll_result=0)  # leader 已退出
        with mock.patch.object(proc_utils, "os", _OsWithoutGetpgid()), \
            mock.patch.object(pal, "IS_WINDOWS", True), \
            mock.patch.object(pal, "stdin_eof", return_value=True), \
            mock.patch.object(pal, "kill_tree",
                              side_effect=lambda pid, sig, **kw:
                              (sigs.append(sig), True)[1]):
            kill_process_group(
                popen, sigterm_only_if_alive=True, caller="test")
        # 既有口径：leader 已退出跳过 TERM 段，无条件补刀 SIGKILL 仍在
        assert sigs == [pal.SIGKILL]

    def test_win32_sigkill_only_if_group_alive_probe_dead_early_out(self):
        sigs = []
        popen = _FakePopen(pid=9)
        with mock.patch.object(proc_utils, "os", _OsWithoutGetpgid()), \
            mock.patch.object(pal, "IS_WINDOWS", True), \
            mock.patch.object(pal, "stdin_eof", return_value=True), \
            mock.patch.object(pal, "kill_tree",
                              side_effect=lambda pid, sig, **kw:
                              (sigs.append(sig), sig != 0)[1]):
            kill_process_group(
                popen, sigkill_only_if_group_alive=True, caller="test")
        # 探活（信号 0）报组已清空 → 免补刀提前收口
        assert sigs == [pal.SIGTERM, 0]

    def test_posix_branch_unaffected(self):
        # Linux：hasattr(os,"getpgid") 恒真；假 pid 触 ProcessLookupError
        # 回退 pgid=pid（既有回退语义），击杀序列逐位不变
        sigs = []
        popen = _FakePopen(pid=4242)
        with mock.patch.object(pal, "kill_tree",
                               side_effect=lambda pid, sig, **kw:
                               (sigs.append((pid, sig)), True)[1]):
            kill_process_group(popen, caller="test")
        assert sigs == [(4242, pal.SIGTERM), (4242, pal.SIGKILL)]


# ── 5.3 dashboard 客户端断连静音 ─────────────────────────────────────


def _bare_handler():
    from core.dashboard.server import DashboardHandler

    handler = object.__new__(DashboardHandler)
    handler.close_connection = False
    return handler


class TestDashboardDisconnectSilence:
    """handle_one_request 边界断连族异常 debug 单行（A6）。"""

    @pytest.mark.parametrize("exc_type", [
        ConnectionResetError,
        ConnectionAbortedError,
        BrokenPipeError,
    ])
    def test_disconnect_family_silenced_to_debug(self, caplog, exc_type):
        handler = _bare_handler()
        with mock.patch.object(
                BaseHTTPRequestHandler, "handle_one_request",
                side_effect=exc_type("peer gone")), \
            caplog.at_level(logging.DEBUG, logger="fenixd.dashboard.server"):
            handler.handle_one_request()
        # 不上抛 + 残连接作废
        assert handler.close_connection is True
        records = [r for r in caplog.records if "断连" in r.getMessage()]
        assert records and max(
            r.levelno for r in records) <= logging.DEBUG

    def test_non_disconnect_errors_propagate(self):
        # 守卫不扩面：业务/其它 socket 异常保持基类上抛语义
        handler = _bare_handler()
        with mock.patch.object(
                BaseHTTPRequestHandler, "handle_one_request",
                side_effect=ValueError("boom")):
            with pytest.raises(ValueError):
                handler.handle_one_request()
        assert handler.close_connection is False
