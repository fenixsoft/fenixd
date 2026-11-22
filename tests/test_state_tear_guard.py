"""STATE.md 空读撕窗守卫回归（v0.1.4 实测 item 6）。

Windows 上写侧原子 replace 的窗口里，读者偶发读出空白（AV/索引器/SMB 抖动），
真机一轮 6 次。守卫：空白但 size>0 → 短重试；耗尽 → warning + 空串（上层
自愈）。合法空文件（size==0）不触发重试。
"""

import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.state_machine import StateParser


class _FakeLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, _tag, msg):
        self.warnings.append(msg)

    def debug(self, *_a):
        pass


def _write(path: Path, content: str):
    path.write_text(content, encoding="utf-8")


def test_tear_guard_retries_then_recovers():
    """首轮空白、重试读回真内容 → 返回解析结果，无耗尽告警。"""
    real = "### demo\n- status: done\n- priority: 5\n"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "STATE.md"
        _write(p, real)
        calls = {"n": 0}
        orig_read = Path.read_text

        def flaky(self, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return ""
            return orig_read(self, *a, **kw)

        with mock.patch.object(Path, "read_text", flaky):
            specs = StateParser.parse(p)
        assert calls["n"] >= 2, "空白后必须重试而非直接返回空"
        assert "demo" in specs, "重试应读回真内容"


def test_tear_guard_exhausted_returns_empty_with_warning():
    """持续空白（size>0）→ 重试耗尽返回空串，留 warning 供对账。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "STATE.md"
        _write(p, "### demo\n- status: done\n")
        log = _FakeLogger()
        with mock.patch.object(Path, "read_text", lambda self, *a, **kw: ""):
            specs = StateParser.parse(p, log)
        assert specs == {}
        assert any("空读重试耗尽" in w for w in log.warnings), log.warnings


def test_legit_empty_file_no_retry():
    """size==0 的合法空 STATE → 直接空解析，零告警零重试。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "STATE.md"
        p.write_text("", encoding="utf-8")
        log = _FakeLogger()
        calls = {"n": 0}
        orig_read = Path.read_text

        def counting(self, *a, **kw):
            if self == p:
                # 只计被测文件自身：类级补丁是全进程的，前序用例泄漏的告警
                # 轮询线程（读 admin_alerts.json 等）落进 with 窗口会虚增计数
                # （regression-1795321244 实证）——守卫是否重试只体现为对本
                # 文件的再读。
                calls["n"] += 1
            return orig_read(self, *a, **kw)

        with mock.patch.object(Path, "read_text", counting):
            specs = StateParser.parse(p, log)
        assert specs == {}
        assert calls["n"] == 1, "合法空文件不得进入重试"
        assert log.warnings == []


def test_normal_read_single_call():
    """正常内容单次读出 → 不进重试分支（守卫零开销路径）。"""
    real = "### demo\n- status: drafted\n- priority: 5\n"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "STATE.md"
        _write(p, real)
        calls = {"n": 0}
        orig_read = Path.read_text

        def counting(self, *a, **kw):
            if self == p:
                # 只计被测文件自身：类级补丁是全进程的，前序用例泄漏的告警
                # 轮询线程（读 admin_alerts.json 等）落进 with 窗口会虚增计数
                # （regression-1795321244 实证）——守卫是否重试只体现为对本
                # 文件的再读。
                calls["n"] += 1
            return orig_read(self, *a, **kw)

        with mock.patch.object(Path, "read_text", counting):
            specs = StateParser.parse(p)
        assert calls["n"] == 1
        assert "demo" in specs
