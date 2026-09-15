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

    # 事件日志（时间戳必须是最近时间，get_recent_events 按分钟窗口过滤）
    (proot / ".fenix" / "logs" / "fenixd-2026.log").write_text(
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
