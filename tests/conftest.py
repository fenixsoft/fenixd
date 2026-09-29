import sys
from pathlib import Path

# ── 夹具骨架排除（fixture 项目自带测试不属 fenixd 回归）────────────────────
# tests/fixtures/scheduling-showcase/ 是验证夹具骨架（见其 README），内含夹具
# 项目自己的 tests/test_schedset.py，依赖 scheduling_showcase 包（不在 fenixd
# sys.path 上）。被 pytest tests/ 收集会在收集期 ModuleNotFoundError 中断整轮
# 回归。该目录内放 conftest.py 不行——与根 tests/conftest.py 同名，pytest 按
# basename 导入会撞名（ImportError: cannot import name ... from 'conftest'）。
# 故在此集中排除。
collect_ignore_glob = ["fixtures/scheduling-showcase/tests/*"]

# Add project root to sys.path for test discovery
# This ensures that 'core' module can be imported from test files
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# ── 收集期导入硬守卫（fix-root-init-import-shadow）─────────────────────────
# 仓库根 __init__.py（08-16 迁移遗留）曾把 /root/fenixd 标记为同名包 fenixd，
# 使 pytest 执行期 sys.path 命中 /root 时 `import fenixd` 被解析为空包而非
# 守护脚本模块 fenixd.py，下游静默 AttributeError。该包标记已随根因删除，
# 此处部署守卫：一旦守卫重现（如回滚不当重新引入 __init__.py），收集阶段
# 即显式硬失败，而非降级为用例执行期的静默 AttributeError。
try:
    import fenixd as _guard_fenixd
except ImportError as _guard_import_err:
    raise ImportError(
        f"import fenixd 失败（{_guard_import_err}）；请检查是否误删 fenixd.py"
    ) from _guard_import_err
if (
    Path(getattr(_guard_fenixd, "__file__", "")).name != "fenixd.py"
    and not hasattr(_guard_fenixd, "FenixDaemon")
):
    raise ImportError(
        "import fenixd 被同名包截胡（仓库根 __init__.py）：解析到 "
        f"{getattr(_guard_fenixd, '__file__', '<unknown>')}，而非守护脚本模块 "
        "fenixd.py。请删除仓库根 __init__.py 恢复 import 解析。"
    )

# ── Dashboard 测试共享夹具（自 test_dashboard_api.py 收敛，行为逐字等价）────
import json
import threading
from datetime import datetime, timezone

import pytest
from unittest import mock

from core.dashboard.registry import Registry
from core.dashboard.server import DashboardHTTPServer, find_free_port


@pytest.fixture(autouse=True, scope="session")
def _disable_verify_engine_reload():
    """测试进程禁用 verify_engine 热重载（常驻 daemon 专属设计）。

    ``pm_engine/verification.py`` 的 ``_run_three_stage_verification`` 开头对
    ``core.verify_engine.*`` 模块链做 ``importlib.reload`` 以支持生产 daemon
    常驻进程热更新。测试进程每个 pytest 会话都是新解释器，模块已是最新，
    reload 反而把 ``TestScenario``/``VerifyEngine`` 等类对象换新——使收集阶段
    绑定的旧类与 reload 后新类 ``isinstance`` 判定分裂，场景在 engine.run 里被
    静默丢弃（2026-09-11 全量回归：test_planready → test_verify_cli_runner 等
    18 个失败，summary.passed 恒 0）。项目内无任何测试依赖真 reload（既有
    fasttrack_orphan_planner_race / cancel_holdstate 等均点状 patch no-op），
    故在会话级统一禁用，消除「忘了 patch 就污染下游」的踩坑面。
    """
    with mock.patch("importlib.reload", lambda m: m):
        yield


@pytest.fixture(autouse=True, scope="session")
def _zero_post_ready_settle():
    """测试进程把探针通过后的静置秒数降为 0。

    ``_finalize_static`` 在生产中于就绪探针通过后固定静置
    ``POST_READY_SETTLE_SECONDS``（10s，白屏 env 事故第三道纵深）。该静置是
    真实墙钟等待，凡走 ``_ensure_app_reachable`` 的用例（9 个文件）各自白等
    10s；测试进程内无「冷实例后端收尾」长尾，静置无语义价值，故会话级置 0。
    静置行为本身由 test_verdict_evidence_taxonomy.TestPostReadySettle 用
    ``patch.object`` 断言原值（该用例自带 patch，不受本 fixture 影响）。
    """
    from core.pm_engine import verification as _vmod

    saved = _vmod.POST_READY_SETTLE_SECONDS
    _vmod.POST_READY_SETTLE_SECONDS = 0
    try:
        yield
    finally:
        _vmod.POST_READY_SETTLE_SECONDS = saved


@pytest.fixture(autouse=True, scope="session")
def _isolated_basetemp_cleanup(request):
    """会话级：把 tmp_path 根隔离到项目 .fenix/，并在会话结束自清（清理方案 A+B）。

    背景：pytest 默认 basetemp 落 ``/tmp/pytest-of-<user>/``，多项目/多并发套件
    共用同一基址；pytest 仅在会话结束清理自己那一层并保留 ~5 个历史目录，长期
    累积到 GB 级（实测单机 1.4G / 33k 条目），且 tmp_path 的 ``make_numbered_dir``
    每用例扫一次目录，随条目数线性变慢。

    A：basetemp 改到 ``<project_root>/.fenix/pytest-basetemp``（gitignored，随
    项目隔离，--basetemp 由 run_full_suite.py 注入；此处兜底直接跑 pytest 的场景）。
    B：会话结束 ``shutil.rmtree`` 本次 basetemp，杜绝跨会话累积。

    对**给定 basetemp**（--basetemp 传入）pytest 会先清空再建——故即使上一轮
    进程被 SIGKILL 未走本清理，下一轮也从干净目录起跑，不会无限增长。

    C：进程级 ``GIT_CEILING_DIRECTORIES`` 钉到 basetemp 根，切断 git 仓库向上
    发现。成因：basetemp 落在 fenixd 仓库内部（``.fenix/pytest-basetemp``，gitignore
    仅挡提交、不挡发现）→ 用例在 ``tmp_path`` 里再建临时目录时，任何不加 ``-C``
    的 ``git`` 调用都会经父目录链上溯命中 /root/fenixd/.git 主树。典型假失败：
    自省摘要 `_collect_recent_commits` 对「非 git 目录」本该降级为「（git log
    读取失败）」，却读到**主树提交**→ 降级分支永不触发（2026-09-22 全量回归
    ``TestSummaryGitCommits::test_daily_summary_git_unavailable_degrades``）。
    钉 ceiling 使 tmp 树对 git 呈「非仓库」态，与 /tmp 落点语义一致。仅设一次
    （setdefault）：尊重任何既有 ceiling。
    """
    import os
    import shutil

    factory = request.session.config._tmp_path_factory
    # 若调用方未指定 basetemp，兜底指到项目内（与 run_full_suite.py 同落点）。
    if factory._basetemp is None and factory._given_basetemp is None:
        project_root = Path(__file__).resolve().parent.parent
        base = project_root / ".fenix" / "pytest-basetemp"
        base.parent.mkdir(parents=True, exist_ok=True)
        factory._given_basetemp = base
    # C：git 仓库发现上溯不得越过 basetemp 根（见 docstring）。
    base = factory._basetemp or factory._given_basetemp
    if base is not None:
        existing = os.environ.get("GIT_CEILING_DIRECTORIES")
        os.environ.setdefault(
            "GIT_CEILING_DIRECTORIES",
            str(base) + ((os.pathsep + existing) if existing else ""),
        )
    yield
    # 会话结束清理本次 basetemp（given 或自建），忽略失败（并发/权限）。
    try:
        if base is not None:
            shutil.rmtree(base, ignore_errors=True)
    except Exception:
        pass


# ── 单用例超时豁免清单（add-per-test-timeout-gate）─────────────────────────
# 全局门：pytest.ini timeout=10（signal）。确需超过 10s 的用例在
# tests/timeout-allowlist.yaml 显式登记（nodeid + timeout_seconds + reason），
# 钩子在收集期按 nodeid 逐字匹配注入 pytest.mark.timeout(N) 覆盖单用例阈值。
# 清单 schema（reason 非空、timeout_seconds > 0、YAML 可解析）由
# tests/test_timeout_gate.py::TestTimeoutAllowlistSchema 机械校验——违规判
# 测试失败（防静默豁免）；注入侧对不可解析清单只告警不炸收集。

import warnings

TIMEOUT_ALLOWLIST_PATH = Path(__file__).resolve().parent / "timeout-allowlist.yaml"


def load_timeout_allowlist(path=None):
    """读取豁免清单，返回 (entries, error)。

    entries：原始条目列表（逐条合法性交给 validate_timeout_allowlist /
    tests/test_timeout_gate.py 的 schema 校验）；文件缺失按空清单处理；
    YAML 解析失败或顶层结构非法时返回 ([], 原因文本)——调用方决定告警或判失败。
    """
    allowlist_path = path or TIMEOUT_ALLOWLIST_PATH
    if not allowlist_path.exists():
        return [], None
    try:
        import yaml

        data = yaml.safe_load(allowlist_path.read_text(encoding="utf-8"))
    except Exception as exc:  # yaml.YAMLError / 编码异常：清单不可解析
        return [], f"豁免清单 YAML 解析失败：{exc!r}"
    if data is None:
        data = {"entries": []}
    if not (isinstance(data, dict) and isinstance(data.get("entries"), list)):
        return [], (
            "豁免清单顶层须为 {entries: [...]} 映射（entries 为条目列表），"
            f"实际 {type(data).__name__}"
        )
    return data["entries"], None


def validate_timeout_allowlist(entries):
    """逐条校验豁免清单条目，返回违规描述列表（空列表 = 合法）。

    校验规则（防静默豁免）：nodeid 非空字符串；timeout_seconds 为 >0 数值
    （布尔不算数）；reason 非空字符串——豁免必须写明为何 10s 不够。
    """
    violations = []
    if not isinstance(entries, list):
        return [f"清单须为条目列表，实际 {type(entries).__name__}"]
    for idx, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            violations.append(
                f"第 {idx} 条：条目须为映射（nodeid/timeout_seconds/reason），"
                f"实际 {type(entry).__name__}"
            )
            continue
        where = f"第 {idx} 条"
        nodeid = entry.get("nodeid")
        if not isinstance(nodeid, str) or not nodeid.strip():
            violations.append(
                f"{where}：nodeid 缺失或为空（须与 pytest --collect-only 输出逐字一致）"
            )
        else:
            where = f"第 {idx} 条（{nodeid}）"
        seconds = entry.get("timeout_seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds <= 0:
            violations.append(f"{where}：timeout_seconds 须为 >0 的数值，实际 {seconds!r}")
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            violations.append(f"{where}：reason 缺失或为空（豁免必须写明为何 10s 不够）")
    return violations


def _usable_allowlist_entry(entry):
    """钩子注入仅认结构合法的条目（条目级违规由 schema 校验用例拦截上报）。"""
    seconds = entry.get("timeout_seconds") if isinstance(entry, dict) else None
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("nodeid"), str)
        and isinstance(seconds, (int, float))
        and not isinstance(seconds, bool)
        and seconds > 0
    )


def pytest_collection_modifyitems(config, items):
    """豁免清单注入（add-per-test-timeout-gate 任务 2.2）。

    按 nodeid 逐字匹配清单条目，命中即注入 pytest.mark.timeout(N) 覆盖全局
    10s 门。清单不可解析时发 warning 并放弃本轮注入（不炸收集）；条目级违规
    由 tests/test_timeout_gate.py::TestTimeoutAllowlistSchema 在回归中判失败。
    """
    entries, error = load_timeout_allowlist()
    if error is not None:
        warnings.warn(f"单用例超时豁免清单不可用，本轮未注入任何豁免：{error}")
        return
    by_nodeid = {
        entry["nodeid"]: entry for entry in entries if _usable_allowlist_entry(entry)
    }
    for item in items:
        entry = by_nodeid.get(item.nodeid)
        if entry is not None:
            item.add_marker(pytest.mark.timeout(entry["timeout_seconds"]))


def make_project(tmp_path: Path, name: str = "proj-a", otherspec: bool = True) -> Path:
    """构造一个可用的 Fenixd 项目目录。

    otherspec=False 时 STATE.md 不含 otherspec 条目（原 test_dashboard_watcher
    本地变体）；默认 True 与原 test_dashboard_api 版逐字节一致。
    """
    proot = tmp_path / name
    (proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "verify-progress" / "myspec" / "screenshots").mkdir(parents=True, exist_ok=True)
    (proot / "spec" / "changes" / "myspec" / "specs").mkdir(parents=True, exist_ok=True)

    state_body = (
        "# Fenix Project State\n\n## Specs\n\n"
        "### myspec\n- status: testing\n- priority: 2\n- created: 2026-01-01T00:00:00+00:00\n"
        "- updated: 2026-01-02T00:00:00+00:00\n- error: null\n- depends_on: null\n"
    )
    if otherspec:
        state_body += (
            "\n### otherspec\n- status: done\n- priority: 1\n- created: 2026-02-01T00:00:00+00:00\n"
            "- updated: 2026-02-02T00:00:00+00:00\n- error: null\n- depends_on: null\n"
        )
    (proot / ".fenix" / "STATE.md").write_text(state_body, encoding="utf-8")

    (proot / ".fenix" / "config.yaml").write_text("project:\n  name: fake\n", encoding="utf-8")

    (proot / "spec" / "changes" / "myspec" / "tasks.md").write_text(
        "## 1. 阶段一\n\n"
        "- [x] 1.1 任务一\n"
        "- [ ] 1.2 任务二\n\n"
        "## 2. 阶段二\n\n"
        "- [ ] 2.1 任务三\n",
        encoding="utf-8",
    )

    (proot / "spec" / "changes" / "myspec" / "specs" / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: 功能\n\n"
        "#### Scenario: 场景一\n- **WHEN** x\n- **THEN** y\n\n"
        "#### Scenario: 场景二\n- **WHEN** a\n- **THEN** b\n",
        encoding="utf-8",
    )

    # 验证产物
    (proot / ".fenix" / "verify-progress" / "myspec.json").write_text(
        json.dumps({"total": 3, "done": 1, "current": "场景二"}), encoding="utf-8"
    )
    (proot / ".fenix" / "verify-progress" / "myspec" / "report.json").write_text(
        json.dumps({
            "summary": {"total": 2, "passed": 1, "failed": 1, "warnings": 0, "errors": 0},
            "scenarios": [
                {"scenario_id": "sc-1", "status": "pass", "description": "通过场景",
                 "assertion_results": [{"type": "element_visible", "pass": True}]},
                {"scenario_id": "sc-2", "status": "fail", "description": "失败场景",
                 "assertion_results": [{"type": "text_match", "pass": False,
                                        "message": "期望 '5' 实际 'x'"}],
                 "screenshots": ["fail.png"]},
            ],
        }), encoding="utf-8"
    )
    (proot / ".fenix" / "verify-progress" / "myspec" / "test_scenarios.json").write_text(
        json.dumps([{"id": "sc-1"}, {"id": "sc-2"}]), encoding="utf-8"
    )
    (proot / ".fenix" / "verify-progress" / "myspec" / "screenshots" / "fail.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    # 运行记录（一条已完成 + 一条运行中）
    (proot / ".fenix" / "runs" / "impl-myspec-1780000000.jsonl").write_text(
        json.dumps({"type": "system", "subtype": "init"}, ensure_ascii=False) + "\n"
        + json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "开始实现"}]}}, ensure_ascii=False) + "\n"
        + json.dumps({"type": "result", "result": "完成", "num_turns": 5}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (proot / ".fenix" / "runs" / "verify-myspec-1780001000.jsonl").write_text(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "playwright_cli", "input": {"action": "click"}}]}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # 事件日志（时间戳必须是最近时间，get_recent_events 按分钟窗口过滤）。
    # 文件名用 FlockRotatingFileHandler 真实命名 fenixd.log（轮转备份为
    # fenixd.log.N）；旧值 fenixd-2026.log 是生产端不会产生的失真名，
    # get_recent_events 的 glob（fenixd.log*）匹配不到会假失败。
    (proot / ".fenix" / "logs" / "fenixd.log").write_text(
        json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "level": "INFO",
                    "component": "pm_engine", "message": "scan"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    (proot / "spec" / "changes" / "myspec" / "verification-report.md").write_text(
        "# 验证报告\n\n## Bug 汇总\n- 严重缺陷：点击保存按钮无反应\n  根因：事件未绑定\n",
        encoding="utf-8",
    )
    return proot


class _TestServer:
    """在临时目录上启动 DashboardHTTPServer，线程后台运行。"""

    def __init__(self, registry: Registry, static_dir: Path):
        self.port = find_free_port(20000)
        self.httpd = DashboardHTTPServer(("127.0.0.1", self.port), registry, static_dir)
        self.thread = threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.05), daemon=True)
        self.thread.start()

    def get(self, path: str, raw: bool = False):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            if raw:
                return resp.status, resp.getheader("Content-Type"), body
            return resp.status, json.loads(body)
        finally:
            conn.close()

    def get_ex(self, path: str, headers: dict | None = None):
        """GET 的扩展形态：可带请求头，返回 (status, 响应头 dict, body bytes)。

        条件请求用例（add-dashboard-paging-and-etag 1.4）需要读 ETag 响应头
        与原始空体；既有 get() 语义零改动，本方法独立并行。
        """
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path, headers=headers or {})
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, {k: v for k, v in resp.getheaders()}, body
        finally:
            conn.close()

    def _req(self, method: str, path: str):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path)
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, json.loads(body)
        finally:
            conn.close()

    def post(self, path: str):
        return self._req("POST", path)

    def post_json(self, path: str, payload: dict):
        import http.client
        body = json.dumps(payload).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(
                "POST", path, body=body,
                headers={"Content-Type": "application/json",
                         "Content-Length": str(len(body))},
            )
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, json.loads(data)
        finally:
            conn.close()

    def delete(self, path: str):
        return self._req("DELETE", path)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def server_fx(tmp_path):
    proot = make_project(tmp_path)
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
    yield proot, srv
    srv.stop()
