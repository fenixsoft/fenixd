"""test-dashboard-architecture-api — 项目架构图后端测试（add-project-architecture-tab 3.1）。

覆盖（spec「生成生命周期治理」/「产物权威判定」/「skill 可用性」）：
- POST refresh 受理异步落盘与 ready（diagram.html 落盘 + 状态查询 ready）
- 在飞重复 POST 409（per-project 单飞，不产生第二个 claude 进程）
- 产物缺失/为空但 claude 自述完成 → failed（权威判定不信自述）
- 组件数越界（>16）→ failed，错误含实际数量与允许范围
- skill 安装失败 → failed，error 原样携带 `npx skills add tt-a1i/archify -g`
- 超时 → 进程组击杀 + failed（错误注明超时）
- daemon 重启残留 generating → 读侧合成 failed（中断）
- failed 后重试 → 正常受理，旧错误被覆盖

测试隔离双陷阱对策（对齐 test_freeze_stop_inflight_agents 布防先例）：
fake Popen 按 cmd[0] 分发（claude → 生成进程 / npx → skill 安装）；
``claude_started`` Event 布防「fake 已被调起」、``claude_block_event`` 布防
「线程停在 communicate」——测试先等布防哨再断言在飞窗口，杜绝受理时序
竞态假失败；生成线程为 daemon 线程，收尾必 set 阻塞哨不留悬挂。
"""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: F401 — 与既有 dashboard 测试同款导入形态

from conftest import _TestServer, make_project  # noqa: E402
from core.dashboard.registry import Registry  # noqa: E402


def _registry(tmp_path, proot):
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    return reg


def _server(tmp_path, proot):
    static = Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static"
    return _TestServer(_registry(tmp_path, proot), static)


DIAGRAM_HTML = "<!DOCTYPE html><html><body>architecture</body></html>"


def _write_diagram(proot: Path, content: str = DIAGRAM_HTML):
    d = proot / ".fenix" / "architecture"
    d.mkdir(parents=True, exist_ok=True)
    (d / "diagram.html").write_text(content, encoding="utf-8")


def _arm_skill(tmp_path, monkeypatch):
    """布防 skill 探测：CLAUDE_CONFIG_DIR 指向测试沙箱且预置 SKILL.md
    （探测必命中，安装分支不被触发）；Path.home 同改指沙箱，双候选都
    落在 tmp 内，不依赖测试机真实 ~/.claude 状态。"""
    cfg = tmp_path / "cfg"
    skill = cfg / "skills" / "archify"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text("---\nname: archify\n---\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    import pathlib

    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    return cfg


def _disarm_skill(tmp_path, monkeypatch):
    """布防 skill 缺失：双候选均落空 → 走安装分支（npx fake 接管）。"""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg-absent"))
    import pathlib

    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)


def _fake_popen(
    monkeypatch,
    *,
    claude_stdout="",
    claude_returncode=0,
    claude_raise=None,
    claude_block_event=None,
    claude_started=None,
    npx_returncode=0,
    npx_raise=None,
    on_claude_run=None,
    seen=None,
):
    """patch subprocess.Popen 为按 cmd[0] 分发的 fake（绝不真跑）：

    - ``claude`` → 生成进程：communicate 返回 claude_stdout（或抛
      claude_raise / 阻塞于 claude_block_event）；on_claude_run(cmd, cwd)
      在被调时执行（模拟 claude 落盘产物）；claude_started 在 Popen 被调
      时 set（布防：测试先观测受理再断言）。
    - ``npx`` → skill 安装（subprocess.run 底层同为 Popen）：returncode /
      communicate 抛 npx_raise。
    """
    import subprocess as _sp

    seen = {} if seen is None else seen

    class _FakeProc:
        # 不存在的 pid：超时路径 getpgid/killpg 落 ProcessLookupError → kill() 兜底
        pid = 999_999_999

        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.returncode = claude_returncode if cmd[0] == "claude" else npx_returncode
            if cmd[0] == "claude":
                seen["claude_cmd"] = cmd
                seen["claude_kwargs"] = kwargs
                if on_claude_run is not None:
                    on_claude_run(cmd, kwargs.get("cwd"))
                if claude_started is not None:
                    claude_started.set()
            else:
                seen["npx_cmd"] = cmd

        def communicate(self, timeout=None):
            if self.cmd[0] == "npx":
                if npx_raise is not None:
                    raise npx_raise
                return "", "npx stderr"
            if claude_raise is not None:
                raise claude_raise
            if claude_block_event is not None:
                # 最长等 5s：测试收尾必 set，daemon 线程不悬挂
                claude_block_event.wait(5.0)
            return claude_stdout, ""

        def kill(self):
            seen["killed"] = True

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(_sp, "Popen", _FakeProc)
    return seen


def _poll_status(srv, until, timeout=5.0):
    """轮询状态直至 until(body) 为真（异步生成落盘有线程时延，布防后轮询
    权威判定结果）；超时返回最后一次 body 供断言报错。"""
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        _, body = srv.get("/api/architecture/status?project=proj-a")
        if until(body):
            return body
        time.sleep(0.05)
    return body


class TestArchitectureStatusAPI:
    """GET /api/architecture/status 基础契约。"""

    def test_none_when_never_generated(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        _arm_skill(tmp_path, monkeypatch)
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/architecture/status?project=proj-a")
            assert status == 200
            assert body["state"] == "none"
            assert body["generated_at"] is None
            assert body["error"] is None
        finally:
            srv.stop()

    def test_unknown_project_404(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        _arm_skill(tmp_path, monkeypatch)
        srv = _server(tmp_path, proot)
        try:
            status, _ = srv.get("/api/architecture/status?project=nope")
            assert status == 404
        finally:
            srv.stop()

    def test_restart_residual_generating_synthesized_failed(self, tmp_path, monkeypatch):
        """status.json 残留 generating 且在飞线程不在 → 读侧合成 failed（中断）。"""
        proot = make_project(tmp_path)
        _arm_skill(tmp_path, monkeypatch)
        d = proot / ".fenix" / "architecture"
        d.mkdir(parents=True)
        (d / "status.json").write_text(
            json.dumps({"state": "generating", "started_at": "2026-01-01T00:00:00+00:00"}),
            encoding="utf-8",
        )
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/architecture/status?project=proj-a")
            assert status == 200
            assert body["state"] == "failed"
            assert "中断" in body["error"]
        finally:
            srv.stop()


class TestArchitectureDiagramAPI:
    """GET /api/architecture/diagram 下发与结构化错误。"""

    def test_not_generated_structured_error(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        _arm_skill(tmp_path, monkeypatch)
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/architecture/diagram?project=proj-a")
            assert status == 404
            assert body["code"] == "architecture_not_generated"
        finally:
            srv.stop()

    def test_ready_serves_html(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        _arm_skill(tmp_path, monkeypatch)
        _write_diagram(proot)
        d = proot / ".fenix" / "architecture"
        (d / "status.json").write_text(
            json.dumps({"state": "ready", "generated_at": "2026-01-01T00:00:00+00:00"}),
            encoding="utf-8",
        )
        srv = _server(tmp_path, proot)
        try:
            status, ctype, body = srv.get(
                "/api/architecture/diagram?project=proj-a", raw=True
            )
            assert status == 200
            assert ctype.startswith("text/html")
            assert b"architecture" in body
        finally:
            srv.stop()


class TestArchitectureRefreshAPI:
    """POST /api/architecture/refresh 受理 / 单飞 / 判定链。"""

    def test_accept_and_ready(self, tmp_path, monkeypatch):
        """受理异步落盘：POST 立即返回受理，生成完成后 diagram.html 存在、
        状态查询 ready 且带生成完成时间与组件数。"""
        proot = make_project(tmp_path)
        _arm_skill(tmp_path, monkeypatch)
        seen = _fake_popen(
            monkeypatch,
            claude_stdout="分析完成\nARCHIFY_DONE 12",
            on_claude_run=lambda cmd, cwd: _write_diagram(proot),
        )
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.post_json("/api/architecture/refresh?project=proj-a", {})
            assert status == 200
            assert body["ok"] is True
            assert body["state"] == "generating"
            final = _poll_status(srv, lambda b: b["state"] != "generating")
            assert final["state"] == "ready", final
            assert final["generated_at"]
            assert final["component_count"] == 12
            assert final["error"] is None
            assert (proot / ".fenix" / "architecture" / "diagram.html").is_file()
        finally:
            srv.stop()

    def test_inflight_duplicate_post_409(self, tmp_path, monkeypatch):
        """在飞期间重复 POST → 409（单飞，不产生第二个 claude 进程）。"""
        proot = make_project(tmp_path)
        _arm_skill(tmp_path, monkeypatch)
        started = threading.Event()
        block = threading.Event()
        calls = []
        _fake_popen(
            monkeypatch,
            claude_stdout="ARCHIFY_DONE 10",
            claude_block_event=block,
            claude_started=started,
            on_claude_run=lambda cmd, cwd: calls.append(1) or _write_diagram(proot),
        )
        srv = _server(tmp_path, proot)
        try:
            status, _ = srv.post_json("/api/architecture/refresh?project=proj-a", {})
            assert status == 200
            # 布防门控：先等 fake claude 被调起（此刻线程必停在 communicate、
            # 单飞锁被持有），再断言在飞窗口的拒绝语义
            assert started.wait(5.0)
            status2, _ = srv.post_json("/api/architecture/refresh?project=proj-a", {})
            assert status2 == 409
            assert len(calls) == 1  # 未产生第二个生成进程
        finally:
            block.set()  # 收尾放行线程，不留悬挂
            srv.stop()

    def test_artifact_missing_claimed_done_failed(self, tmp_path, monkeypatch):
        """claude 自述完成但 diagram.html 缺失 → failed，MUST NOT 进入 ready。"""
        proot = make_project(tmp_path)
        _arm_skill(tmp_path, monkeypatch)
        _fake_popen(
            monkeypatch,
            claude_stdout="已完成，架构图已生成\nARCHIFY_DONE 10",
            # on_claude_run 缺席：不落盘产物
        )
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "缺失" in (final["error"] or "")
        finally:
            srv.stop()

    def test_component_count_out_of_range_failed(self, tmp_path, monkeypatch):
        """组件数越界（20 > 16）→ failed，错误含实际数量与允许范围。"""
        proot = make_project(tmp_path)
        _arm_skill(tmp_path, monkeypatch)
        _fake_popen(
            monkeypatch,
            claude_stdout="ARCHIFY_DONE 20",
            on_claude_run=lambda cmd, cwd: _write_diagram(proot),
        )
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "20" in (final["error"] or "")
            assert "8" in (final["error"] or "") and "16" in (final["error"] or "")
            assert final["component_count"] == 20
        finally:
            srv.stop()

    def test_skill_install_failure_error_carries_command(self, tmp_path, monkeypatch):
        """skill 缺失且自动安装失败 → failed，error 原样含安装命令文本。"""
        proot = make_project(tmp_path)
        _disarm_skill(tmp_path, monkeypatch)
        _fake_popen(monkeypatch, npx_returncode=1)
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "npx skills add tt-a1i/archify -g" in (final["error"] or "")
        finally:
            srv.stop()

    def test_skill_install_timeout_error_carries_command(self, tmp_path, monkeypatch):
        """skill 自动安装超时 → failed，error 同样带安装命令（人工兜底）。"""
        proot = make_project(tmp_path)
        _disarm_skill(tmp_path, monkeypatch)
        _fake_popen(
            monkeypatch,
            npx_raise=subprocess.TimeoutExpired(cmd="npx", timeout=120),
        )
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "npx skills add tt-a1i/archify -g" in (final["error"] or "")
        finally:
            srv.stop()

    def test_timeout_kills_process_group(self, tmp_path, monkeypatch):
        """communicate 超时 → 进程组击杀（fake pid 不可查时 kill 兜底），
        状态 failed 且错误注明超时。"""
        proot = make_project(tmp_path)
        _arm_skill(tmp_path, monkeypatch)
        seen = _fake_popen(
            monkeypatch,
            claude_raise=subprocess.TimeoutExpired(cmd="claude", timeout=1800),
        )
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "超时" in (final["error"] or "")
            assert seen.get("killed") is True
        finally:
            srv.stop()

    def test_invocation_shape_and_env(self, tmp_path, monkeypatch):
        """spawn 形态：claude -p <prompt> --permission-mode bypassPermissions，
        cwd=项目根，start_new_session=True；env 剔除 agent-run 专用三键。"""
        proot = make_project(tmp_path)
        _arm_skill(tmp_path, monkeypatch)
        monkeypatch.setenv("FENIX_RUN_PROJECT_ROOT", "/should/be/stripped")
        monkeypatch.setenv("FENIX_RUN_WORKTREE", "/should/be/stripped")
        monkeypatch.setenv("CLAUDE_CODE_ENABLE_TODO_TOOLS", "1")
        seen = _fake_popen(
            monkeypatch,
            claude_stdout="ARCHIFY_DONE 10",
            on_claude_run=lambda cmd, cwd: _write_diagram(proot),
        )
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            _poll_status(srv, lambda b: b["state"] == "ready")
            cmd = seen["claude_cmd"]
            assert cmd[0] == "claude"
            assert "-p" in cmd
            assert "bypassPermissions" in cmd
            # 提示词含形态契约与 marker 协议（组装正确性抽检）
            prompt = " ".join(cmd)
            assert "ARCHIFY_DONE" in prompt
            assert "8–16" in prompt
            kwargs = seen["claude_kwargs"]
            assert Path(kwargs["cwd"]) == proot
            assert kwargs["start_new_session"] is True
            env = kwargs["env"]
            assert "FENIX_RUN_PROJECT_ROOT" not in env
            assert "FENIX_RUN_WORKTREE" not in env
            assert "CLAUDE_CODE_ENABLE_TODO_TOOLS" not in env
        finally:
            srv.stop()

    def test_retry_after_failure_overwrites_error(self, tmp_path, monkeypatch):
        """failed 后重试：正常受理并开始新一轮，旧失败原因被覆盖（ready 后
        error 归空、generated_at 刷新）。"""
        proot = make_project(tmp_path)
        _arm_skill(tmp_path, monkeypatch)
        # 第一轮：claude 自述完成但产物缺失 → failed
        _fake_popen(monkeypatch, claude_stdout="ARCHIFY_DONE 10")
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            first = _poll_status(srv, lambda b: b["state"] == "failed")
            assert first["state"] == "failed", first
            # 第二轮：产物落盘 → ready，旧错误被覆盖
            _fake_popen(
                monkeypatch,
                claude_stdout="ARCHIFY_DONE 9",
                on_claude_run=lambda cmd, cwd: _write_diagram(proot),
            )
            status, _ = srv.post_json("/api/architecture/refresh?project=proj-a", {})
            assert status == 200
            second = _poll_status(srv, lambda b: b["state"] == "ready")
            assert second["state"] == "ready", second
            assert second["error"] is None
            assert second["generated_at"]
            assert second["component_count"] == 9
        finally:
            srv.stop()
