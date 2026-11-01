"""run 注入提示词落盘/读取测试（add-run-prompt-viewer）。

覆盖 spec 全部 Scenario：
- 提示词落盘为 run 事件行：_run_agent spawn 前写点、恰一行且位于首个 CLI
  事件之前、车道全覆盖（impl + administrator）、写失败（OSError）不阻断派发；
- 读取数据层 get_run_prompt：全文逐字节一致、历史 run（无 prompt 行）返回
  prompt=null、已归档 run 经 archive 回退可读、坏行跳过不崩、读失败
  error="unreadable"；
- HTTP 端点 GET /api/runs/<run_id>/prompt：含记录 run 返回全文、历史 run
  prompt=null、未知项目走既有 {"error": "unknown project"} 200 字典契约、
  空/尾斜杠 run_id 400。
"""

import io
import json
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 共享夹具（make_project / _TestServer / server_fx）与 runs API 端点测试同源
from conftest import _TestServer  # noqa: E402

from core.dashboard import data as dash_data  # noqa: E402
from core.dashboard.registry import Registry  # noqa: E402
from core.proc_utils import find_free_port  # noqa: E402


# ── _run_agent 写点测试基建（与 test_run_latency_stats 同款替身形态） ──

def _make_runner(proot):
    from test_agent_runner import make_runner

    runner = make_runner(proot)
    runner.config = {"agents": {"run_timeout_seconds": 3600}}
    # 轮询环取消旗标所需最小实例状态（make_runner 跳过 __init__ 未初始化）
    runner._cancel_requested = set()
    runner._cancel_requested_lock = threading.Lock()
    runner._cancel_meta = {}
    return runner


def _fake_subprocess(events, returncode=0):
    """Popen 替身：stdout 产出 stream-json 事件行，进程随即以 rc 退出。"""
    class _FakeProc:
        def __init__(self):
            self.stdout = io.StringIO(
                "".join(json.dumps(e) + "\n" for e in events))
            self.stderr = io.StringIO("")
            # stdin 写端（_feed_stdin 线程 write 后 close；StringIO 足够）
            self.stdin = io.StringIO("")
            self.returncode = returncode
            self.pid = 4242

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

        def terminate(self):
            pass

        def kill(self):
            pass

    proc = _FakeProc()
    ns = SimpleNamespace(
        Popen=lambda *a, **k: proc,
        PIPE=subprocess.PIPE,
        TimeoutExpired=subprocess.TimeoutExpired,
    )
    return ns, proc


def _read_lines(proot, run_id):
    run_file = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    return [json.loads(line) for line in
            run_file.read_text(encoding="utf-8").splitlines() if line.strip()]


# ── Requirement: 注入提示词落盘为 run 事件行 ─────────────────────────


class TestRunPromptWritePoint:
    """Scenario: impl run 落盘提示词 / 写失败不阻断派发 / 车道全覆盖。"""

    PROMPT = "实现 X 功能——完整注入提示词\n多行正文（含中文与\"引号\"）"

    def _cli_events(self):
        return [
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "开工"}]}},
            {"type": "result", "result": "完成", "num_turns": 1},
        ]

    def test_impl_run_writes_prompt_before_first_cli_event(self, tmp_path):
        """impl run 经 _run_agent 派发 → 产物含恰一行 type:"prompt"，
        text 与注入提示词逐字节一致，且行位置在首个 CLI 事件之前。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        fake_ns, _proc = _fake_subprocess(self._cli_events(), returncode=0)
        import core.agent_runner.runner as rmod
        with mock.patch.object(rmod, "subprocess", fake_ns):
            runner._run_agent(self.PROMPT, proot, "impl-prompt-1",
                              spec_name="prompt-spec", agent_type="impl")
        lines = _read_lines(proot, "impl-prompt-1")
        prompt_idx = [i for i, l in enumerate(lines) if l.get("type") == "prompt"]
        assert len(prompt_idx) == 1, f"应恰一行 prompt 事件，实际 {len(prompt_idx)}"
        idx = prompt_idx[0]
        assert lines[idx]["text"] == self.PROMPT
        # timestamp 为 UTC ISO8601（datetime.fromisoformat 可解析且带时区偏移）
        ts = datetime.fromisoformat(lines[idx]["timestamp"])
        assert ts.utcoffset() is not None and ts.utcoffset().total_seconds() == 0
        # 首个 CLI 事件（system/assistant/user）之前
        first_cli = next(i for i, l in enumerate(lines)
                         if l.get("type") in ("system", "assistant", "user"))
        assert idx < first_cli

    def test_prompt_write_oserror_does_not_block_dispatch(self, tmp_path):
        """prompt 行写入抛 OSError（如目录只读）→ run 照常 spawn 与执行收尾，
        无异常上抛、CLI 事件转录照常落盘。

        monkeypatch 口径：仅首个 append_run_line 调用（即 Popen 前的 prompt
        写点——_run_agent 内线程启动前唯一一次调用）抛 OSError，其后调用
        委托真实实现；全量替换会让转录写盘一并失败，无法区分「写点容错」
        与「整条写盘链路瘫痪」。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        fake_ns, _proc = _fake_subprocess(self._cli_events(), returncode=0)
        import core.agent_runner.runner as rmod
        real_append = rmod.append_run_line
        calls = {"n": 0}

        def _fail_first(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("disk full")
            return real_append(*args, **kwargs)

        with mock.patch.object(rmod, "append_run_line",
                               side_effect=_fail_first), \
             mock.patch.object(rmod, "subprocess", fake_ns):
            # 不抛异常即通过：OSError 被写点容错吞掉，派发主路径不受阻
            runner._run_agent(self.PROMPT, proot, "impl-prompt-2",
                              spec_name="prompt-spec", agent_type="impl")
        assert calls["n"] >= 2, "写点失败后派发必须继续（后续写盘调用仍发生）"
        lines = _read_lines(proot, "impl-prompt-2")
        # spawn 照常发生：CLI 事件转录与 result 终态照常落盘
        assert [l["type"] for l in lines if l.get("type") == "result"] == ["result"]
        assert all(l.get("type") != "prompt" for l in lines)

    def test_prompt_lane_coverage_admin_and_impl(self, tmp_path):
        """车道全覆盖：administrator 车道与 impl 车道各派发一次 run，两个产物
        各含一行 type:"prompt"，text 分别为各自车道的完整注入提示词。

        administrator 属派发前连通预检白名单，预检替身短路（测试环境无
        网关域名依赖，不探测）。
        """
        from core.agent_runner.runner import AgentRunner

        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        admin_prompt = "administrator 车道注入提示词"
        impl_prompt = "impl 车道注入提示词"
        fake_ns, _proc = _fake_subprocess(self._cli_events(), returncode=0)
        import core.agent_runner.runner as rmod
        with mock.patch.object(AgentRunner, "_dispatch_connectivity_preflight",
                               create=True, new=lambda *a, **k: None), \
             mock.patch.object(rmod, "subprocess", fake_ns):
            runner._run_agent(impl_prompt, proot, "impl-prompt-3",
                              spec_name="prompt-spec", agent_type="impl")
            runner._run_agent(admin_prompt, proot, "admin-prompt-3",
                              spec_name=None, agent_type="administrator")
        assert _read_lines(proot, "impl-prompt-3")[
            [l.get("type") for l in _read_lines(proot, "impl-prompt-3")].index("prompt")
        ]["text"] == impl_prompt
        admin_lines = _read_lines(proot, "admin-prompt-3")
        admin_prompt_lines = [l for l in admin_lines if l.get("type") == "prompt"]
        assert len(admin_prompt_lines) == 1
        assert admin_prompt_lines[0]["text"] == admin_prompt


# ── Requirement: 数据层 get_run_prompt ───────────────────────────────


class TestGetRunPromptDataLayer:
    """Scenario: 全文逐字节一致 / 历史 run null / 归档回退 / 坏行容错。"""

    PROMPT_TEXT = "完整提示词全文：第一步……第二步……\n(特殊字符 \"\\ ⽇)"

    @staticmethod
    def _write_run(proot, run_id, events):
        runs_dir = proot / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        p = runs_dir / f"{run_id}.jsonl"
        p.write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
            encoding="utf-8")
        return p

    def test_exact_prompt_line_returned(self, tmp_path):
        proot = tmp_path / "proj"
        self._write_run(proot, "impl-x-1", [
            {"type": "prompt", "text": self.PROMPT_TEXT, "timestamp": "2026-01-01T00:00:00+00:00"},
            {"type": "system", "subtype": "init"},
            {"type": "result", "result": "ok"},
        ])
        result = dash_data.get_run_prompt(proot, "impl-x-1")
        assert result == {
            "run_id": "impl-x-1",
            "exists": True,
            "prompt": self.PROMPT_TEXT,
            "recorded_at": "2026-01-01T00:00:00+00:00",
            "error": None,
        }

    def test_missing_file_exists_false(self, tmp_path):
        proot = tmp_path / "proj"
        (proot / ".fenix" / "runs").mkdir(parents=True)
        result = dash_data.get_run_prompt(proot, "impl-ghost-1")
        assert result["exists"] is False
        assert result["prompt"] is None
        assert result["error"] is None

    def test_historical_run_without_prompt_line(self, tmp_path):
        """历史 run（功能上线前产物，无 prompt 行）→ prompt=None、不报错。"""
        proot = tmp_path / "proj"
        self._write_run(proot, "impl-old-1", [
            {"type": "system", "subtype": "init"},
            {"type": "result", "result": "ok"},
        ])
        result = dash_data.get_run_prompt(proot, "impl-old-1")
        assert result["exists"] is True
        assert result["prompt"] is None
        assert result["recorded_at"] is None
        assert result["error"] is None

    def test_archived_run_resolved_via_archive_fallback(self, tmp_path):
        proot = tmp_path / "proj"
        arch = proot / ".fenix" / "runs" / "archive"
        arch.mkdir(parents=True)
        (arch / "impl-arch-1.jsonl").write_text(
            json.dumps({"type": "prompt", "text": "归档提示词",
                        "timestamp": "2026-01-02T00:00:00+00:00"},
                       ensure_ascii=False) + "\n",
            encoding="utf-8")
        result = dash_data.get_run_prompt(proot, "impl-arch-1")
        assert result["exists"] is True
        assert result["prompt"] == "归档提示词"

    def test_bad_lines_skipped(self, tmp_path):
        """含坏行（半行 JSON / 非 dict 行）的产物跳过坏行不崩，仍命中 prompt 行。"""
        proot = tmp_path / "proj"
        runs_dir = proot / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        (runs_dir / "impl-bad-1.jsonl").write_text(
            '{"type": "prompt", "text": "坏行之前的提示词", "timestamp": "t0"}\n'
            '{"type": "assistant", "mess\n'          # 半行 JSON（截断）
            '[1, 2, 3]\n'                             # 合法 JSON 非 dict 行
            'not-json-at-all\n'                       # 纯垃圾行
            '{"type": "result", "result": "ok"}\n',
            encoding="utf-8")
        result = dash_data.get_run_prompt(proot, "impl-bad-1")
        assert result["prompt"] == "坏行之前的提示词"
        assert result["error"] is None

    def test_oserror_reports_unreadable(self, tmp_path):
        proot = tmp_path / "proj"
        self._write_run(proot, "impl-io-1", [{"type": "result"}])
        target = proot / ".fenix" / "runs" / "impl-io-1.jsonl"
        orig_open = Path.open

        def _deny_open(self, *a, **kw):
            if str(self) == str(target):
                raise OSError("permission denied")
            return orig_open(self, *a, **kw)

        with mock.patch.object(Path, "open", _deny_open):
            result = dash_data.get_run_prompt(proot, "impl-io-1")
        assert result["exists"] is True
        assert result["prompt"] is None
        assert result["error"] == "unreadable"


# ── Requirement: HTTP 端点 ───────────────────────────────────────────


class TestRunPromptEndpoint:
    """Scenario: 查看含记录 run / 未知项目契约 / 空 run_id 400。"""

    @staticmethod
    def _make_server(tmp_path):
        from conftest import make_project

        proot = make_project(tmp_path, otherspec=False)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787,
                  "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": []})
        srv = _TestServer(
            reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        return proot, srv

    def test_endpoint_returns_recorded_prompt(self, tmp_path):
        proot, srv = self._make_server(tmp_path)
        try:
            runs_dir = proot / ".fenix" / "runs"
            prompt_text = "端到端提示词全文 ✅"
            (runs_dir / "impl-web-1.jsonl").write_text(
                json.dumps({"type": "prompt", "text": prompt_text,
                            "timestamp": "2026-01-03T00:00:00+00:00"},
                           ensure_ascii=False) + "\n"
                + json.dumps({"type": "result", "result": "ok"}) + "\n",
                encoding="utf-8")
            status, data = srv.get("/api/runs/impl-web-1/prompt?project=proj-a")
            assert status == 200
            assert data["ok"] is True
            assert data["run_id"] == "impl-web-1"
            assert data["prompt"] == prompt_text
            assert data["recorded_at"] == "2026-01-03T00:00:00+00:00"
            assert data["project"] == "proj-a"
        finally:
            srv.stop()

    def test_endpoint_historical_run_prompt_null(self, tmp_path):
        proot, srv = self._make_server(tmp_path)
        try:
            # conftest make_project 预置 impl-myspec-1780000000（无 prompt 行）
            status, data = srv.get(
                "/api/runs/impl-myspec-1780000000/prompt?project=proj-a")
            assert status == 200
            assert data["ok"] is True
            assert data["prompt"] is None
        finally:
            srv.stop()

    def test_endpoint_unknown_project_contract(self, tmp_path):
        _, srv = self._make_server(tmp_path)
        try:
            status, data = srv.get("/api/runs/impl-x-1/prompt?project=ghost")
            assert status == 200
            assert data == {"error": "unknown project"}
        finally:
            srv.stop()

    def test_endpoint_empty_or_trailing_slash_run_id_400(self, tmp_path):
        _, srv = self._make_server(tmp_path)
        try:
            # 空/尾斜杠变体 400 防线：`/api/runs/foo//prompt` 经 (.+) 捕获到
            # "foo/"（尾斜杠 id），prompt 路由显式 400（_get_runs_watch 同款）
            status, _ = srv.get("/api/runs/foo//prompt?project=proj-a")
            assert status == 400
            # 尾随斜杠整体（/prompt/ 后缀）不落 prompt 路由，由兜底 runs 路由
            # 既有尾斜杠 400 防线收口
            status, _ = srv.get("/api/runs/impl-x-1/prompt/?project=proj-a")
            assert status == 400
            # 双斜杠空 id（//prompt）regex (化.+) 捕获 "/prompt" 落兜底路由，
            # 数据层白名单按不存在处理 → 200+prompt:null 契约，不 500 即可
            status, _ = srv.get("/api/runs//prompt?project=proj-a")
            assert status in (200, 400, 404)
        finally:
            srv.stop()


# 模块级 find_free_port 引用保持（与 conftest 同源导入面；避免未用告警）
_ = find_free_port
