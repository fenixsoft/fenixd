"""test-dashboard-architecture-api — 项目架构图后端测试（add-project-architecture-tab 3.1；
fix-archify-vendored-injection / add-architecture-two-stage-generation 改造）。

覆盖（spec「两段式生成管线」/「evidence 取证复用与 HEAD 指纹失效」/
「生成生命周期治理」/「产物权威判定」/「archify skill 可用性保障」）：
- POST refresh 受理异步落盘与 ready（diagram.html 落盘 + 状态查询 ready）
- 两段式管线：阶段1 探索（写 evidence.md，marker ARCHIFY_EVIDENCE_DONE）
  → 阶段2 出图（绝对路径引用 SKILL.md/evidence，marker ARCHIFY_DONE），
  两段 prompt 均不内嵌 SKILL.md 全文
- evidence HEAD 指纹：HEAD 一致跳过阶段1（只 spawn 一次）/ HEAD 变化或
  evidence 缺失·损坏·无指纹头重探索
- 阶段1 判定链：returncode==0 且 evidence 非空才进阶段2，失败短路
- 分段超时：阶段1/阶段2 各自进程组击杀，error 文案含阶段前缀
- status.json stage 键：exploring/authoring 运行态与终态 null
- 在飞重复 POST 409（per-project 单飞，不产生第二个生成进程）
- 产物缺失/为空但 claude 自述完成 → failed（权威判定链不变）
- 组件数越界（>16）→ failed，错误含实际数量与允许范围
- vendored SKILL.md 缺失/为空 → failed，文案注明部署损坏并对照 VENDORED.md
  恢复，全程未发起任何安装动作（零安装进程）
- daemon 重启残留 generating → 读侧合成 failed（中断）
- failed 后重试 → 正常受理，旧错误被覆盖

测试隔离双陷阱对策（对齐 test_freeze_stop_inflight_agents 布防先例）：
fake Popen 按函数形态 patch，按 prompt 内容区分阶段——含
``ARCHIFY_EVIDENCE_DONE`` 即阶段1 探索 run、含 ``ARCHIFY_DONE`` marker
契约即阶段2 出图 run；非 claude 命令（HEAD 指纹探针的 git 调用）记录后
放行真实执行。「全程只派生 claude 与 git 探针」由测试对记录断言，而非
依赖 fake 只认得 claude；``started`` Event 布防「fake 已被调起」、
``block_event`` 布防「线程停在 communicate」——测试先等布防哨再断言
在飞窗口，杜绝受理时序竞态假失败；生成线程为 daemon 线程，收尾必 set
阻塞哨并等终态落盘，不留悬挂。「vendored 缺件」经 monkeypatch
``_vendored_skill_root()`` 指向临时目录构造，MUST NOT 增删/改写真实
``vendor/archify/`` 下任何文件。
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

EVIDENCE_MD = (
    "# 架构取证材料\n\n"
    "## 核心组件\n- dashboard routes：HTTP 端点层\n"
    "## 主链路\n浏览器 → routes → manager → claude\n"
    "## 外部依赖\n- bigmodel 网关\n"
    "## 信任边界\nHTTP query 输入在路由层校验\n"
)


def _write_diagram(proot: Path, content: str = DIAGRAM_HTML):
    d = proot / ".fenix" / "architecture"
    d.mkdir(parents=True, exist_ok=True)
    (d / "diagram.html").write_text(content, encoding="utf-8")


def _write_evidence(proot: Path, content: str = EVIDENCE_MD):
    d = proot / ".fenix" / "architecture"
    d.mkdir(parents=True, exist_ok=True)
    (d / "evidence.md").write_text(content, encoding="utf-8")


def _noop(cmd, cwd):
    """显式 no-op on_run：模拟 claude 未落盘任何产物。"""


def _git_repo_with_head(proot: Path) -> str:
    """把 tmp 项目初始化为 git 仓库并产生一个 HEAD 提交，返回 HEAD sha。"""
    def _git(*args: str) -> str:
        out = subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=str(proot), capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()

    _git("init", "-q")
    _git("config", "user.email", "test@example.com")
    _git("config", "user.name", "test")
    (proot / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git("add", "-A")
    _git("commit", "-q", "-m", "init")
    return _git("rev-parse", "HEAD")


class _Stage:
    """一段 claude run 的 fake 行为描述（on_run=None 表示未指定，由
    _fake_popen 按阶段补默认落盘行为；显式传 _noop 表示不落盘）。"""

    def __init__(self, *, stdout="", returncode=0, raise_exc=None,
                 block_event=None, started=None, on_run=None):
        self.stdout = stdout
        self.returncode = returncode
        self.raise_exc = raise_exc
        self.block_event = block_event
        self.started = started
        self.on_run = on_run


def _fill_stage(kind: str, cfg) -> _Stage:
    """补齐阶段默认行为：阶段1 探索落盘非空 evidence.md（stdout 出
    ARCHIFY_EVIDENCE_DONE）；阶段2 出图落盘 diagram.html（stdout 出
    ARCHIFY_DONE 12）。两段默认即 happy path。"""
    if kind == "explore":
        default = _Stage(
            stdout=arch_routes.EVIDENCE_MARKER_PREFIX,
            on_run=lambda cmd, cwd: _write_evidence(Path(cwd)),
        )
    else:
        default = _Stage(
            stdout=f"{arch_routes.ARCHIFY_MARKER_PREFIX} 12",
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


def _fake_popen(monkeypatch, *, explore=None, author=None, seen=None):
    """patch subprocess.Popen 为两段生成进程 fake（claude 绝不真跑）。

    按 prompt 内容分发阶段：cmd 含 ``ARCHIFY_EVIDENCE_DONE`` → 阶段1
    探索 run；含 ``ARCHIFY_DONE`` marker 契约 → 阶段2 出图 run。记录：

    - ``all_cmds``：全部 Popen 命令（含 HEAD 指纹探针的 git 调用）；
    - ``claude_cmds`` / ``stage_cmds``：claude 派生记录（顺序与阶段名）；
    - ``{explore,author}_{cmd,kwargs}``：两段 spawn 形态与参数；
    - ``killed``：超时击杀哨。

    非 claude 命令（git 探针）记录后放行真实执行——``_repo_head`` 需要
    真实 git 输出，且「除 claude 与 git 探针外无其他外部进程」由测试对
    记录断言（vendored 化后链路不应派生 npx 等安装进程）。
    """
    import subprocess as _sp

    _real_popen = _sp.Popen
    seen = {} if seen is None else seen
    seen.setdefault("all_cmds", [])
    seen.setdefault("claude_cmds", [])
    seen.setdefault("stage_cmds", [])
    explore_cfg = _fill_stage("explore", explore)
    author_cfg = _fill_stage("author", author)

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
        if arch_routes.EVIDENCE_MARKER_PREFIX in prompt:
            kind, cfg = "explore", explore_cfg
        elif arch_routes.ARCHIFY_MARKER_PREFIX in prompt:
            kind, cfg = "author", author_cfg
        else:
            # 非 claude 进程（HEAD 指纹 git 探针）：放行真实执行
            return _real_popen(cmd, **kwargs)
        seen["claude_cmds"].append(cmd)
        seen["stage_cmds"].append(kind)
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
                        "stage": "exploring"}),
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


class TestVendoredSkillInjection:
    """vendored 包完整性与两段 prompt 装配（fix-archify-vendored-injection /
    add-architecture-two-stage-generation）。"""

    def test_vendored_missing_failed_deployment_damage(self, tmp_path, monkeypatch):
        """SKILL.md 缺失（vendored 根指向临时空目录）→ failed，文案含
        「部署损坏」与 VENDORED.md 恢复指引，且全程未派生任何外部进程
        （零安装动作；检查先于阶段1 spawn）。真实 vendor/archify/ 不被触碰。"""
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
            # 未发起任何安装动作：完整性检查阶段零外部进程派生（含 git 探针）
            assert seen["all_cmds"] == []
        finally:
            srv.stop()

    def test_vendored_empty_skill_md_failed(self, tmp_path, monkeypatch):
        """SKILL.md 存在但为空文件 → 同判 failed（部署损坏语义一致）。"""
        proot = make_project(tmp_path)
        pkg = tmp_path / "vendored-empty-file"
        pkg.mkdir()
        (pkg / "SKILL.md").write_text("", encoding="utf-8")
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

    def test_prompts_reference_abs_paths_without_fulltext(self, tmp_path, monkeypatch):
        """两段 prompt 均不内嵌 vendored SKILL.md 全文（大上下文请求实测
        被网关静默丢弃），改以绝对路径引用；阶段1 探索 prompt 含四项取证
        维度、evidence 写盘绝对路径与 EVIDENCE marker；阶段2 出图 prompt
        含 SKILL.md/evidence 绝对路径、本地无网校验指引、五项形态约束、
        分段小步写纪律与 ARCHIFY_DONE marker。"""
        proot = make_project(tmp_path)
        skill_md_text = (
            arch_routes._vendored_skill_root() / "SKILL.md"
        ).read_text(encoding="utf-8")
        skill_root = str(arch_routes._vendored_skill_root())
        evidence_abs = str(
            (proot / ".fenix" / "architecture" / "evidence.md").resolve()
        )
        explore_prompt = arch_routes._build_explore_prompt(proot, "proj-a")
        author_prompt = arch_routes._build_author_prompt(proot, "proj-a")
        # 两段均不内嵌全文（也不注入包根目录供探索段绕读）
        assert skill_md_text not in explore_prompt
        assert skill_md_text not in author_prompt
        assert skill_root not in explore_prompt
        # 阶段1：evidence 写盘路径 + marker 契约 + 组件规模口径
        assert evidence_abs in explore_prompt
        assert arch_routes.EVIDENCE_MARKER_PREFIX in explore_prompt
        assert "8–16" in explore_prompt
        assert "只读" in explore_prompt
        # 阶段2：绝对路径引用 + 校验指引 + 形态约束 + 分段写盘纪律
        assert skill_root in author_prompt
        assert "SKILL.md" in author_prompt
        assert evidence_abs in author_prompt
        assert "node bin/archify.mjs" in author_prompt
        assert "请使用 archify skill" not in author_prompt
        assert arch_routes.ARCHIFY_MARKER_PREFIX in author_prompt
        assert "8–16" in author_prompt
        assert "Edit" in author_prompt  # 先骨架后逐段 Edit 补全
        assert "单次巨量 Write" in author_prompt  # 禁单次巨量写
        # 小上下文安全区：两段 prompt 都远小于全文内嵌形态（SKILL.md 实测 16KB）
        assert len(explore_prompt) < 2000
        assert len(author_prompt) < 4000

    def test_generation_spawns_only_claude_and_git_probe(self, tmp_path, monkeypatch):
        """整条两段链路派生的外部进程只有 claude（两段）与 HEAD 指纹探针
        的 git 调用（rev-parse/symbolic-ref）：无 npx 等任何安装动作进程
        （vendored 零联网安装原则）。"""
        proot = make_project(tmp_path)
        seen = _fake_popen(monkeypatch)
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "ready")
            assert final["state"] == "ready", final
            assert seen["claude_cmds"], "生成链路应派生 claude"
            assert all(c[0] == "claude" for c in seen["claude_cmds"])
            for c in seen["all_cmds"]:
                assert c[0] in ("claude", "git"), seen["all_cmds"]
                if c[0] == "git":
                    assert c[1] in ("rev-parse", "symbolic-ref"), c
        finally:
            srv.stop()


class TestEvidenceHeadFingerprint:
    """evidence HEAD 指纹 helper（design D2）：缺失/损坏/无指纹头/HEAD
    变化/detached 一律判不匹配；HEAD 以 proot 为 cwd 取得。"""

    def test_head_match_roundtrip(self, tmp_path):
        proot = make_project(tmp_path)
        sha = _git_repo_with_head(proot)
        _write_evidence(
            proot,
            f"{arch_routes.EVIDENCE_HEAD_PREFIX} {sha} | "
            f"2026-01-01T00:00:00+00:00\n\n{EVIDENCE_MD}",
        )
        assert arch_routes._evidence_head_matches(proot) is True
        assert arch_routes._repo_head(proot) == sha

    def test_missing_empty_or_unstamped_mismatch(self, tmp_path):
        proot = make_project(tmp_path)
        assert arch_routes._evidence_head_matches(proot) is False  # 缺失
        _write_evidence(proot, "")
        assert arch_routes._evidence_head_matches(proot) is False  # 空文件
        _write_evidence(proot, EVIDENCE_MD)  # 无指纹头
        assert arch_routes._evidence_head_matches(proot) is False

    def test_stale_sha_mismatch(self, tmp_path):
        proot = make_project(tmp_path)
        _git_repo_with_head(proot)
        _write_evidence(
            proot,
            f"{arch_routes.EVIDENCE_HEAD_PREFIX} "
            f"{'deadbeef' * 5}0 | 2026-01-01T00:00:00+00:00\n\n{EVIDENCE_MD}",
        )
        assert arch_routes._evidence_head_matches(proot) is False

    def test_corrupt_bytes_mismatch(self, tmp_path):
        proot = make_project(tmp_path)
        path = proot / ".fenix" / "architecture" / "evidence.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe\x00invalid-utf8\x80\x81")
        assert arch_routes._evidence_head_matches(proot) is False

    def test_nongit_project_stamp_unknown_never_matches(self, tmp_path):
        """非 git 项目：HEAD 取不到（None），盖 unknown 指纹且比对恒不匹配
        ——反向覆盖「禁止用进程 cwd 取 HEAD」：若误用 daemon cwd（fenixd
        仓库），这里会盖出真实 sha 并错误命中。"""
        proot = make_project(tmp_path)
        assert arch_routes._repo_head(proot) is None
        _write_evidence(proot, EVIDENCE_MD)
        assert arch_routes._stamp_evidence_head(proot) is True
        first = (
            proot / ".fenix" / "architecture" / "evidence.md"
        ).read_text(encoding="utf-8").splitlines()[0]
        assert first.startswith(arch_routes.EVIDENCE_HEAD_PREFIX)
        assert "unknown" in first
        assert arch_routes._evidence_head_matches(proot) is False

    def test_detached_head_mismatch(self, tmp_path):
        """detached HEAD 按不可复用口径：即使指纹 sha 与当前 commit 一致也
        判不匹配（每次 refresh 重探索）。"""
        proot = make_project(tmp_path)
        sha = _git_repo_with_head(proot)
        subprocess.run(
            ["git", "-c", "advice.detachedHead=false", "checkout", "-q", "--detach"],
            cwd=str(proot), check=True, capture_output=True, text=True,
        )
        _write_evidence(
            proot,
            f"{arch_routes.EVIDENCE_HEAD_PREFIX} {sha} | "
            f"2026-01-01T00:00:00+00:00\n\n{EVIDENCE_MD}",
        )
        assert arch_routes._evidence_head_matches(proot) is False

    def test_restamp_replaces_stale_header(self, tmp_path):
        """重探索后重盖指纹：旧头部（含旧 sha/时间戳）被剥离替换，不残留。"""
        proot = make_project(tmp_path)
        _write_evidence(
            proot,
            f"{arch_routes.EVIDENCE_HEAD_PREFIX} {'c0ffee' * 6} | "
            f"2020-01-01T00:00:00+00:00\n\n{EVIDENCE_MD}",
        )
        assert arch_routes._stamp_evidence_head(proot) is True
        text = (
            proot / ".fenix" / "architecture" / "evidence.md"
        ).read_text(encoding="utf-8")
        assert "c0ffee" not in text  # 旧指纹已剥除
        first = text.splitlines()[0]
        assert first.startswith(arch_routes.EVIDENCE_HEAD_PREFIX)
        assert "unknown" in first  # 非 git 项目 → unknown


class TestArchitectureRefreshAPI:
    """POST /api/architecture/refresh 受理 / 单飞 / 两段编排 / 判定链。"""

    def test_accept_and_ready(self, tmp_path, monkeypatch):
        """受理异步落盘：POST 立即返回受理，两段跑完后 diagram.html 存在、
        状态查询 ready 且带生成完成时间与组件数，终态 stage 归 null。"""
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
            assert seen["stage_cmds"] == ["explore", "author"]
            assert final["generated_at"]
            assert final["component_count"] == 12
            assert final["error"] is None
            assert final["stage"] is None
            assert (proot / ".fenix" / "architecture" / "diagram.html").is_file()
            # 阶段1 产物已盖 HEAD 指纹（非 git 项目 → unknown 哨兵）
            ev_head = (
                proot / ".fenix" / "architecture" / "evidence.md"
            ).read_text(encoding="utf-8").splitlines()[0]
            assert ev_head.startswith(arch_routes.EVIDENCE_HEAD_PREFIX)
        finally:
            srv.stop()

    def test_stage_field_progression_and_terminal_null(self, tmp_path, monkeypatch):
        """stage 键：阶段1 运行中 exploring → 阶段2 运行中 authoring →
        终态 null（向后兼容可选键，读侧透传）。"""
        proot = make_project(tmp_path)
        explore_started = threading.Event()
        author_started = threading.Event()
        explore_block = threading.Event()
        author_block = threading.Event()
        _fake_popen(
            monkeypatch,
            explore=_Stage(block_event=explore_block, started=explore_started),
            author=_Stage(block_event=author_block, started=author_started),
        )
        srv = _server(tmp_path, proot)
        try:
            status, _ = srv.post_json("/api/architecture/refresh?project=proj-a", {})
            assert status == 200
            # 布防门控：fake 被调起时阶段标记必已先行落盘
            assert explore_started.wait(5.0)
            body = _poll_status(srv, lambda b: b.get("stage") == "exploring")
            assert body["stage"] == "exploring", body
            assert body["state"] == "generating"
            explore_block.set()
            assert author_started.wait(5.0)
            body = _poll_status(srv, lambda b: b.get("stage") == "authoring")
            assert body["stage"] == "authoring", body
            author_block.set()
            final = _poll_status(srv, lambda b: b["state"] == "ready")
            assert final["state"] == "ready", final
            assert final["stage"] is None, final
        finally:
            _drain(srv, [explore_block, author_block])
            srv.stop()

    def test_head_match_skips_explore(self, tmp_path, monkeypatch):
        """evidence 存在且 HEAD 指纹一致 → 跳过阶段1 直接出图（重试只付
        出图成本，全程只 spawn 一次 claude）。"""
        proot = make_project(tmp_path)
        _git_repo_with_head(proot)
        seen = _fake_popen(monkeypatch)
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            first = _poll_status(srv, lambda b: b["state"] == "ready")
            assert first["state"] == "ready", first
            assert seen["stage_cmds"] == ["explore", "author"]
            # 第二轮：HEAD 未变 → 只 spawn 阶段2
            seen2 = _fake_popen(monkeypatch)
            status, _ = srv.post_json("/api/architecture/refresh?project=proj-a", {})
            assert status == 200
            second = _poll_status(srv, lambda b: b["state"] == "ready")
            assert second["state"] == "ready", second
            assert second["error"] is None
            assert seen2["stage_cmds"] == ["author"], seen2["stage_cmds"]
        finally:
            srv.stop()

    def test_head_change_reexplores(self, tmp_path, monkeypatch):
        """HEAD 变化 → evidence 指纹失配 → 重新探索（图不因复用而陈旧），
        evidence 头部指纹更新为新 HEAD。"""
        proot = make_project(tmp_path)
        _git_repo_with_head(proot)
        seen = _fake_popen(monkeypatch)
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            first = _poll_status(srv, lambda b: b["state"] == "ready")
            assert first["state"] == "ready", first
            # 推进 HEAD：追加提交
            (proot / "seed.txt").write_text("changed\n", encoding="utf-8")
            subprocess.run(
                ["git", "-c", "commit.gpgsign=false", "add", "-A"],
                cwd=str(proot), check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "v2"],
                cwd=str(proot), check=True, capture_output=True, text=True,
            )
            new_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(proot), check=True, capture_output=True, text=True,
            ).stdout.strip()
            seen2 = _fake_popen(monkeypatch)
            status, _ = srv.post_json("/api/architecture/refresh?project=proj-a", {})
            assert status == 200
            second = _poll_status(srv, lambda b: b["state"] == "ready")
            assert second["state"] == "ready", second
            assert seen2["stage_cmds"] == ["explore", "author"], seen2["stage_cmds"]
            head_line = (
                proot / ".fenix" / "architecture" / "evidence.md"
            ).read_text(encoding="utf-8").splitlines()[0]
            assert new_sha in head_line
        finally:
            srv.stop()

    def test_stage1_nonzero_exit_short_circuit(self, tmp_path, monkeypatch):
        """阶段1 非零退出 → 直接 failed 短路，不 spawn 阶段2。"""
        proot = make_project(tmp_path)
        seen = _fake_popen(monkeypatch, explore=_Stage(returncode=1))
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "阶段1 探索失败" in (final["error"] or "")
            assert "explore_cmd" in seen and "author_cmd" not in seen
        finally:
            srv.stop()

    def test_stage1_evidence_missing_short_circuit(self, tmp_path, monkeypatch):
        """阶段1 退出码为 0 但未落盘 evidence → failed 短路，不 spawn 阶段2
        （判定不信 claude 自述）。"""
        proot = make_project(tmp_path)
        seen = _fake_popen(monkeypatch, explore=_Stage(on_run=_noop))
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "阶段1 探索失败" in (final["error"] or "")
            assert "缺失或为空" in (final["error"] or "")
            assert "author_cmd" not in seen
        finally:
            srv.stop()

    def test_stage1_evidence_empty_short_circuit(self, tmp_path, monkeypatch):
        """阶段1 落盘空 evidence 文件 → 同判 failed 短路。"""
        proot = make_project(tmp_path)
        seen = _fake_popen(
            monkeypatch,
            explore=_Stage(on_run=lambda cmd, cwd: _write_evidence(Path(cwd), "")),
        )
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "缺失或为空" in (final["error"] or "")
            assert "author_cmd" not in seen
        finally:
            srv.stop()

    def test_stage1_timeout_kills_process_group(self, tmp_path, monkeypatch):
        """阶段1 communicate 超时 → 进程组击杀（fake pid 不可查时 kill 兜
        底），failed 且 error 含阶段前缀，不 spawn 阶段2。"""
        proot = make_project(tmp_path)
        seen = _fake_popen(
            monkeypatch,
            explore=_Stage(
                raise_exc=subprocess.TimeoutExpired(cmd="claude", timeout=720)
            ),
        )
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "阶段1 探索超时" in (final["error"] or "")
            assert "720" in (final["error"] or "")
            assert seen.get("killed") is True
            assert "author_cmd" not in seen
        finally:
            srv.stop()

    def test_stage2_timeout_kills_process_group(self, tmp_path, monkeypatch):
        """阶段2 communicate 超时 → 进程组击杀，failed 且 error 含阶段前缀。"""
        proot = make_project(tmp_path)
        seen = _fake_popen(
            monkeypatch,
            author=_Stage(
                raise_exc=subprocess.TimeoutExpired(cmd="claude", timeout=1080)
            ),
        )
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            final = _poll_status(srv, lambda b: b["state"] == "failed")
            assert final["state"] == "failed", final
            assert "阶段2 出图超时" in (final["error"] or "")
            assert "1080" in (final["error"] or "")
            assert seen.get("killed") is True
            assert seen["stage_cmds"] == ["explore", "author"]
        finally:
            srv.stop()

    def test_inflight_duplicate_post_409(self, tmp_path, monkeypatch):
        """在飞期间重复 POST → 409（单飞，不产生第二个生成进程）。"""
        proot = make_project(tmp_path)
        started = threading.Event()
        block = threading.Event()
        seen = _fake_popen(
            monkeypatch, explore=_Stage(block_event=block, started=started)
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
        """阶段2 claude 自述完成但 diagram.html 缺失 → failed，MUST NOT 进入
        ready（产物权威判定链行为与改造前一致）。"""
        proot = make_project(tmp_path)
        _fake_popen(monkeypatch, author=_Stage(on_run=_noop))
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
        _fake_popen(
            monkeypatch,
            author=_Stage(
                stdout=f"{arch_routes.ARCHIFY_MARKER_PREFIX} 20",
                on_run=lambda cmd, cwd: _write_diagram(Path(cwd)),
            ),
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

    def test_invocation_shape_and_env(self, tmp_path, monkeypatch):
        """spawn 形态（两段同款）：claude -p <prompt> --permission-mode
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
            assert seen["stage_cmds"] == ["explore", "author"]
            evidence_abs = str(
                (proot / ".fenix" / "architecture" / "evidence.md").resolve()
            )
            for kind in ("explore", "author"):
                cmd = seen[f"{kind}_cmd"]
                assert cmd[0] == "claude"
                assert "-p" in cmd
                assert "bypassPermissions" in cmd
                kwargs = seen[f"{kind}_kwargs"]
                assert Path(kwargs["cwd"]) == proot
                assert kwargs["start_new_session"] is True
                env = kwargs["env"]
                assert "FENIX_RUN_PROJECT_ROOT" not in env
                assert "FENIX_RUN_WORKTREE" not in env
                assert "CLAUDE_CODE_ENABLE_TODO_TOOLS" not in env
            # 提示词组装抽检：阶段 marker 与交接面路径落在正确的段
            explore_prompt = " ".join(seen["explore_cmd"])
            assert arch_routes.EVIDENCE_MARKER_PREFIX in explore_prompt
            assert evidence_abs in explore_prompt
            author_prompt = " ".join(seen["author_cmd"])
            assert arch_routes.ARCHIFY_MARKER_PREFIX in author_prompt
            assert "8–16" in author_prompt
            assert str(arch_routes._vendored_skill_root()) in author_prompt
        finally:
            srv.stop()

    def test_retry_after_failure_overwrites_error(self, tmp_path, monkeypatch):
        """failed 后重试：正常受理并开始新一轮，旧失败原因被覆盖（ready 后
        error 归空、generated_at 刷新）。"""
        proot = make_project(tmp_path)
        # 第一轮：阶段2 自述完成但产物缺失 → failed
        _fake_popen(monkeypatch, author=_Stage(on_run=_noop))
        srv = _server(tmp_path, proot)
        try:
            srv.post_json("/api/architecture/refresh?project=proj-a", {})
            first = _poll_status(srv, lambda b: b["state"] == "failed")
            assert first["state"] == "failed", first
            # 第二轮：两段 happy path → ready，旧错误被覆盖
            _fake_popen(monkeypatch)
            status, _ = srv.post_json("/api/architecture/refresh?project=proj-a", {})
            assert status == 200
            second = _poll_status(srv, lambda b: b["state"] == "ready")
            assert second["state"] == "ready", second
            assert second["error"] is None
            assert second["generated_at"]
            assert second["component_count"] == 12
        finally:
            srv.stop()
