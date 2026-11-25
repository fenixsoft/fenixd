"""test-dashboard-architecture-api — 项目架构图后端测试（add-project-architecture-tab 3.1；
floorplan 单段式生成管线改造）。

覆盖（spec「单段式生成管线」/「生成生命周期治理」/「产物权威判定」/
「floorplan skill 可用性保障」）：
- POST refresh 受理异步落盘与 ready（diagram.html 落盘 + 状态查询 ready）
- 单段式管线：一个小 prompt 的生成 run（绝对路径引用 SKILL.md/references，
  不内嵌全文），marker FLOORPLAN_DONE <顶层节点数>
- 分段超时（单段 1800s）：进程组击杀，error 文案含超时秒数
- status.json stage 键：mapping 运行态与终态 null
- 在飞重复 POST 409（per-project 单飞，不产生第二个生成进程）
- 产物缺失/为空但 claude 自述完成 → failed（权威判定链不变）
- marker 缺失 → component_count=null 放行（形态校验尽力而为）
- 顶层节点数越界（>9）→ failed，错误含实际数量与允许范围
- 小写 ``<!doctype html>`` 起始产物同判自包含（floorplan 导出形态）
- external 汇点契约：external 出边 → failed（viewer 整图崩溃实测）；边指向
  external → 放行；prompt 含禁止 external 出边的硬性约束
- vendored SKILL.md 缺失/为空 → failed，文案注明部署损坏并对照 VENDORED.md
  恢复，全程未发起任何安装动作（零安装进程）
- daemon 重启残留 generating → 读侧合成 failed（中断）
- failed 后重试 → 正常受理，旧错误被覆盖

测试隔离双陷阱对策（对齐 test_freeze_stop_inflight_agents 布防先例）：
fake Popen 按函数形态 patch，按 prompt 内容分发——含 ``FLOORPLAN_DONE``
marker 契约即生成 run；其余命令记录后放行真实执行。「全程只派生 claude」
由测试对记录断言，而非依赖 fake 只认得 claude；``started`` Event 布防
「fake 已被调起」、``block_event`` 布防「线程停在 communicate」——测试先等
布防哨再断言在飞窗口，杜绝受理时序竞态假失败；生成线程为 daemon 线程，
收尾必 set 阻塞哨并等终态落盘，不留悬挂。「vendored 缺件」经 monkeypatch
``_vendored_skill_root()`` 指向临时目录构造，MUST NOT 增删/改写真实
``vendor/floorplan/`` 下任何文件。
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
from core.dashboard.routes import architecture_routes as arch_routes  # noqa: E402


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
# floorplan --export 产物实测起始形态：小写 doctype（自包含判定同窗）
DIAGRAM_HTML_LOWERCASE = "<!doctype html><html><body>architecture</body></html>"


def _write_diagram(proot: Path, content: str = DIAGRAM_HTML):
    d = proot / ".fenix" / "architecture"
    d.mkdir(parents=True, exist_ok=True)
    (d / "diagram.html").write_text(content, encoding="utf-8")


def _noop(cmd, cwd):
    """显式 no-op on_run：模拟 claude 未落盘任何产物。"""


class _Stage:
    """生成 run 的 fake 行为描述（on_run=None 表示未指定，由 _fake_popen
    补默认落盘行为；显式传 _noop 表示不落盘）。"""

    def __init__(self, *, stdout="", returncode=0, raise_exc=None,
                 block_event=None, started=None, on_run=None):
        self.stdout = stdout
        self.returncode = returncode
        self.raise_exc = raise_exc
        self.block_event = block_event
        self.started = started
        self.on_run = on_run


def _fill_stage(cfg) -> _Stage:
    """补默认行为：落盘非空 diagram.html（stdout 出 FLOORPLAN_DONE 5，
    5 ∈ [3, 9] 形态契约）。默认即 happy path。"""
    default = _Stage(
        stdout=f"{arch_routes.FLOORPLAN_MARKER_PREFIX} 5",
        on_run=lambda cmd, cwd: _write_diagram(Path(cwd)),
    )
    if cfg is None:
        return default
    return _Stage(
        stdout=cfg.stdout or default.stdout,
        returncode=cfg.returncode,
        raise_exc=cfg.raise_exc,
        block_event=cfg.block_event,
        started=cfg.started,
        on_run=cfg.on_run if cfg.on_run is not None else default.on_run,
    )


def _fake_popen(monkeypatch, *, gen=None, seen=None):
    """patch subprocess.Popen 为单段生成进程 fake（claude 绝不真跑）。

    按 prompt 内容分发：cmd 含 ``FLOORPLAN_DONE`` marker 契约 → 生成 run。
    记录：

    - ``all_cmds``：全部 Popen 命令（claude 之外的真实放行也记录）；
    - ``claude_cmds``：claude 派生记录；
    - ``gen_cmd`` / ``gen_kwargs``：spawn 形态与参数；
    - ``killed``：超时击杀哨。

    非 claude 命令记录后放行真实执行——生成链路不应派生任何其他外部
    进程（vendored 零联网零安装原则），由测试对记录断言。
    """
    import subprocess as _sp

    _real_popen = _sp.Popen
    seen = {} if seen is None else seen
    seen.setdefault("all_cmds", [])
    seen.setdefault("claude_cmds", [])
    gen_cfg = _fill_stage(gen)

    class _FakeStageProc:
        # 不存在的 pid：超时路径 getpgid/killpg 落 ProcessLookupError → kill() 兜底
        pid = 999_999_999

        def __init__(self, cfg, cmd, kwargs):
            self.cmd = list(cmd)
            self.returncode = cfg.returncode
            self._cfg = cfg
            if cfg.on_run is not None:
                cfg.on_run(cmd, kwargs.get("cwd"))
            if cfg.started is not None:
                cfg.started.set()

        def communicate(self, timeout=None):
            if self._cfg.raise_exc is not None:
                raise self._cfg.raise_exc
            if self._cfg.block_event is not None:
                # 最长等 5s：测试收尾必 set，daemon 线程不悬挂
                self._cfg.block_event.wait(5.0)
            return self._cfg.stdout, ""

        def kill(self):
            seen["killed"] = True

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

    def _patched_popen(cmd, **kwargs):
        cmd = list(cmd)
        seen["all_cmds"].append(cmd)
        prompt = " ".join(str(c) for c in cmd)
        if arch_routes.FLOORPLAN_MARKER_PREFIX in prompt:
            kind, cfg = "gen", gen_cfg
        else:
            # 非 claude 进程：记录后放行真实执行
            return _real_popen(cmd, **kwargs)
        seen["claude_cmds"].append(cmd)
        seen[f"{kind}_cmd"] = cmd
        seen[f"{kind}_kwargs"] = kwargs
        return _FakeStageProc(cfg, cmd, kwargs)

    monkeypatch.setattr(_sp, "Popen", _patched_popen)
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


def _drain(srv, block_events):
    """收尾放行全部阻塞哨并等终态落盘，不留悬挂 daemon 线程写 tmp 目录。"""
    for ev in block_events:
        ev.set()
    _poll_status(srv, lambda b: b["state"] != "generating")


class TestArchitectureStatusAPI:
    """GET /api/architecture/status 基础契约。"""

    def test_none_when_never_generated(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/architecture/status?project=proj-a")
            assert status == 200
            assert body["state"] == "none"
            assert body["generated_at"] is None
            assert body["error"] is None
            assert body["stage"] is None
        finally:
            srv.stop()

    def test_unknown_project_404(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        srv = _server(tmp_path, proot)
        try:
            status, _ = srv.get("/api/architecture/status?project=nope")
            assert status == 404
        finally:
            srv.stop()

    def test_restart_residual_generating_synthesized_failed(self, tmp_path, monkeypatch):
        """status.json 残留 generating 且在飞线程不在 → 读侧合成 failed（中断）。"""
        proot = make_project(tmp_path)
        d = proot / ".fenix" / "architecture"
        d.mkdir(parents=True)
        (d / "status.json").write_text(
            json.dumps({"state": "generating", "started_at": "2026-01-01T00:00:00+00:00",
                        "stage": "mapping"}),
            encoding="utf-8",
        )
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/architecture/status?project=proj-a")
            assert status == 200
            assert body["state"] == "failed"
            assert "中断" in body["error"]
            assert body["stage"] is None  # 合成中断为终态：stage 归 null
        finally:
            srv.stop()


class TestArchitectureDiagramAPI:
    """GET /api/architecture/diagram 下发与结构化错误。"""

    def test_not_generated_structured_error(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/architecture/diagram?project=proj-a")
            assert status == 404
            assert body["code"] == "architecture_not_generated"
        finally:
            srv.stop()

    def test_ready_serves_html(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
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


class TestVendoredSkillPackage:
    """vendored 包完整性与单段 prompt 装配。"""

    @staticmethod
    def _make_pkg(tmp_path: Path, name: str, *, skill_md: str = "skill"):
        """按 _skill_ready 在位口径（SKILL.md + scan/build/lib/common.mjs）
        构造一个最小 vendored 包目录。"""
        pkg = tmp_path / name
        (pkg / "scripts" / "lib").mkdir(parents=True)
        (pkg / "SKILL.md").write_text(skill_md, encoding="utf-8")
        for rel in ("scripts/scan.mjs", "scripts/build.mjs", "scripts/lib/common.mjs"):
            (pkg / rel).write_text("export {};", encoding="utf-8")
        return pkg

    def test_vendored_missing_failed_deployment_damage(self, tmp_path, monkeypatch):
        """vendored 根指向临时空目录 → failed，文案含「部署损坏」与
        VENDORED.md 恢复指引，且全程未派生任何外部进程（零安装动作；检查
        先于生成 run spawn）。真实 vendor/floorplan/ 不被触碰。"""
        proot = make_project(tmp_path)
        empty = tmp_path / "vendored-absent"
        empty.mkdir()
        monkeypatch.setattr(arch_routes, "_vendored_skill_root", lambda: empty)
        seen = _fake_popen(monkeypatch)
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "部署损坏" in (final["error"] or "")
            assert "VENDORED.md" in (final["error"] or "")
            # 未发起任何安装动作：完整性检查阶段零外部进程派生
            assert seen["all_cmds"] == []
        finally:
            srv.stop()

    def test_vendored_empty_skill_md_failed(self, tmp_path, monkeypatch):
        """SKILL.md 存在但为空文件（其余在位）→ 同判 failed（部署损坏语义
        一致）。"""
        proot = make_project(tmp_path)
        pkg = self._make_pkg(tmp_path, "vendored-empty-file", skill_md="")
        monkeypatch.setattr(arch_routes, "_vendored_skill_root", lambda: pkg)
        _fake_popen(monkeypatch)
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "部署损坏" in (final["error"] or "")
        finally:
            srv.stop()

    def test_vendored_missing_script_failed(self, tmp_path, monkeypatch):
        """SKILL.md 在位但关键脚本（scan.mjs）缺失 → 同判 failed（脚本在位
        检查口径）。"""
        proot = make_project(tmp_path)
        pkg = self._make_pkg(tmp_path, "vendored-missing-script")
        (pkg / "scripts" / "scan.mjs").unlink()
        monkeypatch.setattr(arch_routes, "_vendored_skill_root", lambda: pkg)
        _fake_popen(monkeypatch)
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "部署损坏" in (final["error"] or "")
        finally:
            srv.stop()

    def test_prompt_references_abs_paths_without_fulltext(self, tmp_path, monkeypatch):
        """生成 prompt 不内嵌 vendored SKILL.md 全文（大上下文请求实测被网关
        静默丢弃），改以绝对路径引用 SKILL.md 与 references 契约；含
        FLOORPLAN_UNATTENDED 前缀、scan/build/export 三脚本调用、形态契约
        （3–9 顶层节点）、分段小步写纪律与 FLOORPLAN_DONE marker。"""
        proot = make_project(tmp_path)
        skill_md_text = (
            arch_routes._vendored_skill_root() / "SKILL.md"
        ).read_text(encoding="utf-8")
        skill_root = str(arch_routes._vendored_skill_root())
        prompt = arch_routes._build_generate_prompt(proot, "proj-a")
        # 不内嵌全文，以绝对路径引用包根文件
        assert skill_md_text not in prompt
        assert skill_root in prompt
        assert "SKILL.md" in prompt
        assert "schema.md" in prompt
        assert "choosing-boundaries.md" in prompt
        # 三脚本调用链（scan → build → export）与 unattended 前缀
        assert "FLOORPLAN_UNATTENDED=1" in prompt
        assert "scan.mjs" in prompt
        assert "build.mjs" in prompt
        assert "serve.mjs" in prompt
        # 产物写盘绝对路径与 marker 契约、形态约束、分段写盘纪律
        assert str((proot / ".fenix" / "architecture" / "diagram.html").resolve()) in prompt
        assert arch_routes.FLOORPLAN_MARKER_PREFIX in prompt
        assert "3–9" in prompt
        assert "Edit" in prompt  # 先骨架后逐段 Edit 补全
        assert "单次巨量 Write" in prompt  # 禁单次巨量写
        # 交互特性禁跑（describe/recent/open 等）
        assert "describe.mjs" in prompt
        # 小上下文安全区：远小于全文内嵌形态（SKILL.md 实测 27KB）
        assert len(prompt) < 4000



class TestArchitectureRefreshAPI:
    """POST /api/architecture/refresh 受理 / 单飞 / 单段编排 / 判定链。"""

    def test_accept_and_ready(self, tmp_path, monkeypatch):
        """受理异步落盘：POST 立即返回受理，生成 run 跑完后 diagram.html
        存在、状态查询 ready 且带生成完成时间与顶层节点数，终态 stage 归
        null；两段式管线的 evidence.md 交接面不再存在。"""
        proot = make_project(tmp_path)
        seen = _fake_popen(monkeypatch)
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.post_json("/api/architecture/refresh?project=proj-a", {})
            assert status == 200
            assert body["ok"] is True
            assert body["state"] == "generating"
            final = _poll_status(srv, lambda b: b["state"] != "generating")
            assert final["state"] == "ready", final
            assert len(seen["claude_cmds"]) == 1  # 单段：全程只 spawn 一次 claude
            assert final["generated_at"]
            assert final["component_count"] == 5
            assert final["error"] is None
            assert final["stage"] is None
            assert (proot / ".fenix" / "architecture" / "diagram.html").is_file()
            assert not (proot / ".fenix" / "architecture" / "evidence.md").exists()
        finally:
            srv.stop()

    def test_stage_field_mapping_and_terminal_null(self, tmp_path, monkeypatch):
        """stage 键：运行中 mapping → 终态 null（向后兼容可选键，读侧透传）。"""
        proot = make_project(tmp_path)
        gen_started = threading.Event()
        gen_block = threading.Event()
        _fake_popen(
            monkeypatch,
            gen=_Stage(block_event=gen_block, started=gen_started),
        )
        srv = _server(tmp_path, proot)
        try:
            status, _ = srv.post_json("/api/architecture/refresh?project=proj-a", {})
            assert status == 200
            # 布防门控：fake 被调起时阶段标记必已先行落盘
            assert gen_started.wait(5.0)
            body = _poll_status(srv, lambda b: b.get("stage") == "mapping")
            assert body["stage"] == "mapping", body
            assert body["state"] == "generating"
            gen_block.set()
            final = _poll_status(srv, lambda b: b["state"] == "ready")
            assert final["state"] == "ready", final
            assert final["stage"] is None, final
        finally:
            _drain(srv, [gen_block])
            srv.stop()

    def test_generation_timeout_kills_process_group(self, tmp_path, monkeypatch):
        """生成 run communicate 超时 → 进程组击杀（守卫收口后的 killpg 跳），
        failed 且 error 含超时秒数。"""
        proot = make_project(tmp_path)
        seen = _fake_popen(
            monkeypatch,
            gen=_Stage(
                raise_exc=subprocess.TimeoutExpired(
                    cmd="claude", timeout=arch_routes._GENERATE_TIMEOUT_SECONDS
                )
            ),
        )
        # 击杀哨对齐 add-killpg-self-guard 收口后的最后一跳：清场经
        # guard_killpg 落 killpg（test_dashboard_quality_ocr 同款 recorder）；
        # 不可达 pid 的 proc.kill() 单 pid 降级已按守卫契约（D1）移除。
        killed = []
        monkeypatch.setattr(arch_routes.os, "getpgid", lambda pid: pid)
        monkeypatch.setattr(
            arch_routes.os, "killpg", lambda pgid, sig: killed.append((sig.name, pgid))
        )
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "生成超时" in (final["error"] or "")
            assert str(arch_routes._GENERATE_TIMEOUT_SECONDS) in (final["error"] or "")
            assert ("SIGKILL", 999_999_999) in killed
        finally:
            srv.stop()

    def test_inflight_duplicate_post_409(self, tmp_path, monkeypatch):
        """在飞期间重复 POST → 409（单飞，不产生第二个生成进程）。"""
        proot = make_project(tmp_path)
        started = threading.Event()
        block = threading.Event()
        seen = _fake_popen(
            monkeypatch, gen=_Stage(block_event=block, started=started)
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
            assert len(seen["claude_cmds"]) == 1  # 未产生第二个生成进程
        finally:
            _drain(srv, [block])
            srv.stop()

    def test_artifact_missing_claimed_done_failed(self, tmp_path, monkeypatch):
        """claude 自述完成（stdout 出 marker）但 diagram.html 缺失 → failed，
        MUST NOT 进入 ready（产物权威判定链行为与改造前一致）。"""
        proot = make_project(tmp_path)
        _fake_popen(monkeypatch, gen=_Stage(on_run=_noop))
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "缺失" in (final["error"] or "")
        finally:
            srv.stop()

    def test_artifact_empty_failed(self, tmp_path, monkeypatch):
        """产物落盘为空文件 → 同判 failed（存在且非空口径）。"""
        proot = make_project(tmp_path)
        _fake_popen(
            monkeypatch,
            gen=_Stage(on_run=lambda cmd, cwd: _write_diagram(Path(cwd), "")),
        )
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "缺失或为空" in (final["error"] or "")
        finally:
            srv.stop()

    def test_nonzero_exit_failed(self, tmp_path, monkeypatch):
        """生成 run 非零退出 → failed（不信 claude 自述）。"""
        proot = make_project(tmp_path)
        _fake_popen(monkeypatch, gen=_Stage(returncode=1))
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "非零退出" in (final["error"] or "")
        finally:
            srv.stop()

    def test_not_selfcontained_html_failed(self, tmp_path, monkeypatch):
        """产物存在但缺自包含 HTML 起始特征 → failed。"""
        proot = make_project(tmp_path)
        _fake_popen(
            monkeypatch,
            gen=_Stage(on_run=lambda cmd, cwd: _write_diagram(Path(cwd), "<div>no</div>")),
        )
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "自包含" in (final["error"] or "")
        finally:
            srv.stop()

    def test_lowercase_doctype_accepted(self, tmp_path, monkeypatch):
        """小写 ``<!doctype html>`` 起始产物同判自包含（floorplan --export
        实测形态），判定 ready。"""
        proot = make_project(tmp_path)
        _fake_popen(
            monkeypatch,
            gen=_Stage(
                on_run=lambda cmd, cwd: _write_diagram(Path(cwd), DIAGRAM_HTML_LOWERCASE)
            ),
        )
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] != "generating")
            assert final["state"] == "ready", final
        finally:
            srv.stop()

    def test_marker_missing_count_null_passes(self, tmp_path, monkeypatch):
        """stdout 无 FLOORPLAN_DONE marker → 无法机械校验节点数，记
        component_count=null 放行（形态校验尽力而为，产物可用性优先）。"""
        proot = make_project(tmp_path)
        _fake_popen(monkeypatch, gen=_Stage(stdout="done, no marker here"))
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] != "generating")
            assert final["state"] == "ready", final
            assert final["component_count"] is None
        finally:
            srv.stop()

    def test_component_count_out_of_range_failed(self, tmp_path, monkeypatch):
        """顶层节点数越界（20 > 9）→ failed，错误含实际数量与允许范围。"""
        proot = make_project(tmp_path)
        _fake_popen(
            monkeypatch,
            gen=_Stage(
                stdout=f"{arch_routes.FLOORPLAN_MARKER_PREFIX} 20",
                on_run=lambda cmd, cwd: _write_diagram(Path(cwd)),
            ),
        )
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "20" in (final["error"] or "")
            assert "3" in (final["error"] or "") and "9" in (final["error"] or "")
            assert final["component_count"] == 20
        finally:
            srv.stop()

    @staticmethod
    def _write_arch_json(proot: Path, nodes: list, edges: list) -> None:
        """落盘 floorplan map 的 architecture.json（判定链 best-effort
        汇点校验读取的正是这份文件）。"""
        arch = (
            proot / arch_routes.ARCHITECTURE_DIR / arch_routes.MAP_DIRNAME
        )
        arch.mkdir(parents=True, exist_ok=True)
        (arch / "architecture.json").write_text(
            json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_external_sink_violation_failed(self, tmp_path, monkeypatch):
        """以 external 为 from 的边 → 判定链补校验判 failed（floorplan
        viewer 把 external 钉 ELK LAST 层，external 出边整图渲染崩溃，
        2026-11-25 fenixd 图实测；build.mjs 不校验边方向属上游盲区）。"""
        proot = make_project(tmp_path)

        def _violate(cmd, cwd):
            _write_diagram(Path(cwd))
            self._write_arch_json(
                proot,
                [{"id": "app", "kind": "service", "label": "应用"},
                 {"id": "llm", "kind": "external", "label": "LLM"}],
                [{"from": "llm", "to": "app", "kind": "http"}],
            )

        _fake_popen(monkeypatch, gen=_Stage(on_run=_violate))
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "汇点" in (final["error"] or "")
            assert "llm -> app" in (final["error"] or "")
        finally:
            srv.stop()

    def test_external_sink_clean_edges_passes(self, tmp_path, monkeypatch):
        """边全部指向 external（external 为汇点）→ 汇点校验放行，ready。"""
        proot = make_project(tmp_path)

        def _clean(cmd, cwd):
            _write_diagram(Path(cwd))
            self._write_arch_json(
                proot,
                [{"id": "app", "kind": "service", "label": "应用"},
                 {"id": "llm", "kind": "external", "label": "LLM"}],
                [{"from": "app", "to": "llm", "kind": "http"}],
            )

        _fake_popen(monkeypatch, gen=_Stage(on_run=_clean))
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] != "generating")
            assert final["state"] == "ready", final
        finally:
            srv.stop()

    def test_prompt_forbids_external_outgoing_edges(self, tmp_path, monkeypatch):
        """生成 prompt 含 external 汇点硬性约束：禁止 external 出边，
        external 间关联改用 hosts/packages 字段表达。"""
        proot = make_project(tmp_path)
        prompt = arch_routes._build_generate_prompt(proot, "proj-a")
        assert "汇点" in prompt
        assert "external" in prompt
        assert "hosts/packages" in prompt

    def test_invocation_shape_and_env(self, tmp_path, monkeypatch):
        """spawn 形态：claude -p <prompt> --permission-mode
        bypassPermissions，cwd=项目根，start_new_session=True；env 剔除
        agent-run 专用三键。"""
        proot = make_project(tmp_path)
        monkeypatch.setenv("FENIX_RUN_PROJECT_ROOT", "/should/be/stripped")
        monkeypatch.setenv("FENIX_RUN_WORKTREE", "/should/be/stripped")
        monkeypatch.setenv("CLAUDE_CODE_ENABLE_TODO_TOOLS", "1")
        seen = _fake_popen(monkeypatch)
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            _poll_status(srv, lambda b: b["state"] == "ready")
            cmd = seen["gen_cmd"]
            assert cmd[0] == "claude"
            assert "-p" in cmd
            assert "bypassPermissions" in cmd
            kwargs = seen["gen_kwargs"]
            assert Path(kwargs["cwd"]) == proot
            assert kwargs["start_new_session"] is True
            env = kwargs["env"]
            assert "FENIX_RUN_PROJECT_ROOT" not in env
            assert "FENIX_RUN_WORKTREE" not in env
            assert "CLAUDE_CODE_ENABLE_TODO_TOOLS" not in env
            # 提示词抽检：marker 契约、产物写盘路径与 vendored 包根引用
            prompt = " ".join(seen["gen_cmd"])
            assert arch_routes.FLOORPLAN_MARKER_PREFIX in prompt
            assert str(
                (proot / ".fenix" / "architecture" / "diagram.html").resolve()
            ) in prompt
            assert str(arch_routes._vendored_skill_root()) in prompt
        finally:
            srv.stop()

    def test_retry_after_failure_overwrites_error(self, tmp_path, monkeypatch):
        """failed 后重试：正常受理并开始新一轮，旧失败原因被覆盖（ready 后
        error 归空、generated_at 刷新）。"""
        proot = make_project(tmp_path)
        # 第一轮：自述完成但产物缺失 → failed
        _fake_popen(monkeypatch, gen=_Stage(on_run=_noop))
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            first = _poll_status(srv, lambda b: b["state"] == "failed")
            assert first["state"] == "failed", first
            # 第二轮：happy path → ready，旧错误被覆盖
            _fake_popen(monkeypatch)
            status, _ = srv.post_json("/api/architecture/refresh?project=proj-a", {})
            assert status == 200
            second = _poll_status(srv, lambda b: b["state"] == "ready")
            assert second["state"] == "ready", second
            assert second["error"] is None
            assert second["generated_at"]
            assert second["component_count"] == 5
        finally:
            srv.stop()
