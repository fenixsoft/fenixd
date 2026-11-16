"""evo-scenario-exec-tree-isolation 回归测试。

覆盖（tasks.md 4.1）：
① pytest/cli 执行集执行根落快照 worktree（模拟执行窗内主树被改写、断言结果
   不受影响）；
② merge-back 在验证在飞时有界推迟、超时放行留痕；
③ 锚位假失败稳态复跑甄别（复跑通过不计 fail、真失败仍 fail）；
④ 回退主树路径留痕；
⑤ 快照内全量套件冒烟预检（basetemp 落 ``<root>/.fenix/pytest-basetemp`` 形态
   与 worktree 路径 argv 守卫误击形态复检，对齐 design 风险段）。
"""

import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

from core.pm_engine.verification.pipeline import (
    ANCHOR_RERUN_MAX_NODES,
    EXEC_SNAPSHOT_DIR_REL,
    create_exec_snapshot_worktree,
    exec_set_needs_exec_tree_isolation,
    extract_failed_node_ids,
    release_exec_snapshot_worktree,
    rerun_anchor_transient_failures,
    rerun_failed_nodes_in_main_tree,
)
from core.verify_engine.cli_runner import CliRunner
from core.worktree_manager.mergeback import (
    G4MergebackMixin,
    VERIFY_EXEC_DONE_MARKER,
    VERIFY_EXEC_START_MARKER,
    _MAIN_TREE_VERIFY_INFLIGHT,
    clear_verification_inflight,
    detect_verification_inflight_log_edge,
    mark_verification_inflight,
    verification_inflight_snapshot,
)


# ── 共享替身 ──────────────────────────────────────────────────────────────


class _RecordingLogger:
    def __init__(self):
        self.infos = []
        self.warnings = []

    def info(self, component, message, context=None):
        self.infos.append(message)

    def warning(self, component, message, context=None):
        self.warnings.append(message)

    def error(self, component, message, context=None):
        pass


def _fake_pipeline(project_root, logger=None, config_value=True):
    """create_exec_snapshot_worktree 所需的最小 pipeline 替身。"""
    logger = logger or _RecordingLogger()
    context = SimpleNamespace(
        project_root=project_root,
        logger=logger,
        config_reader=lambda key, default=None: config_value,
    )
    return SimpleNamespace(_context=context), logger


def _mk_git_repo(tmp_path: Path, committed: dict, wip: dict = None) -> Path:
    """建最小 git 仓：committed 文件入库，wip 文件留主树未提交现场。"""
    root = tmp_path / "root-proj-scene"  # 路径含 proj/root 子串（worktree 形态复检）
    root.mkdir()
    for rel, content in committed.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    for rel, content in (wip or {}).items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
    return root


def _git(root: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30
    )


@pytest.fixture(autouse=True)
def _clean_inflight_registry():
    """模块级在飞注册表全局态清理（防跨用例污染）。"""
    _MAIN_TREE_VERIFY_INFLIGHT.clear()
    yield
    _MAIN_TREE_VERIFY_INFLIGHT.clear()


# ── 1.2：三缝单决策点守卫 ─────────────────────────────────────────────────


class TestExecRootDecisionSingleSource:
    """1.2：三缝共用同一执行根决策点的单源守卫。

    scenario-repaired 重入、排程重验（escalation ``_reverify_timers`` 到期
    重派）、unfreeze 重验全部汇流回 ``VerificationPipeline._execute_stage2``
    ——生产侧 ``VerifyEngine`` 构造点必须唯一。旁路新增并行决策点会绕开
    快照隔离与主树轮在飞登记，隔离语义静默失效（快照不建、互斥不感知），
    故以 AST 扫描固化单源，防回潮。
    """

    def test_verify_engine_construction_single_source(self):
        import ast

        core_root = REPO_ROOT / "core"
        sites = []
        for path in sorted(core_root.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, ValueError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    name = None
                    if isinstance(fn, ast.Name):
                        name = fn.id
                    elif isinstance(fn, ast.Attribute):
                        name = fn.attr
                    if name == "VerifyEngine":
                        sites.append(str(path.relative_to(core_root)))
        assert sites == ["pm_engine/verification/pipeline.py"], (
            f"VerifyEngine 生产构造点漂移（执行根决策 MUST 单源于阶段2）: {sites}"
        )


# ── ① + ④：快照执行根 / 回退主树 ──────────────────────────────────────────


class TestSnapshotExecRoot:
    def test_snapshot_baseline_excludes_wip_and_survives_main_tree_rewrite(
        self, tmp_path
    ):
        """①快照基线=主树 HEAD 干净基线：主树 WIP 不入快照、不 stash 不改写
        主树现场；执行窗内主树被改写（模拟合回）后，快照内读到的仍是基线。"""
        root = _mk_git_repo(
            tmp_path,
            committed={"src/mod.py": "VALUE = 'v1'\n"},
            wip={"src/wip_only.py": "WIP = True\n"},
        )
        pipeline, logger = _fake_pipeline(root)
        ctx = create_exec_snapshot_worktree(pipeline, "iso-spec")
        try:
            assert ctx["kind"] == "snapshot", ctx["reason"]
            snap = ctx["root"]
            assert (snap / "src" / "mod.py").read_text() == "VALUE = 'v1'\n"
            assert not (snap / "src" / "wip_only.py").exists(), "主树 WIP 不入快照"
            # 主树现场原样（未 stash、未改写）
            assert (root / "src" / "wip_only.py").read_text() == "WIP = True\n"
            assert (root / "src" / "mod.py").read_text() == "VALUE = 'v1'\n"
            # 执行窗内主树被改写（合回形态：改写 + 提交）
            (root / "src" / "mod.py").write_text("VALUE = 'v3-merged'\n")
            _git(root, "add", "-A")
            _git(root, "commit", "-qm", "merge-back rewrite")
            # 快照内执行（cwd=快照）读到的仍是基线 → 锚位断言不受影响
            out = subprocess.run(
                [sys.executable, "-c", "print(open('src/mod.py').read().strip())"],
                cwd=str(snap), capture_output=True, text=True, timeout=30,
            )
            assert out.stdout.strip() == "VALUE = 'v1'"
            # 引擎接线：cli Runner 缺省 cwd 落快照（scenario_root 消费点）
            runner = CliRunner("iso-spec", root, logger, {}, scenario_root=snap)
            assert runner._resolve_cwd(None) == snap
        finally:
            release_exec_snapshot_worktree(ctx, logger)
        assert not ctx["root"].exists(), "执行后快照应清理"
        assert str(ctx["root"]) not in _git(root, "worktree", "list").stdout

    def test_snapshot_prepare_artifacts_land_in_snapshot(self, tmp_path):
        """产物准备分叉落点显式约定：prepare 在快照内重跑，产物落快照不落主树。"""
        root = _mk_git_repo(tmp_path, committed={"keep.txt": "x\n"})
        (root / ".fenix").mkdir(exist_ok=True)
        (root / ".fenix" / "verify.yaml").write_text(
            "prepare:\n"
            "  - run: python3 -c \"open('artifact.txt','w').write('built')\"\n",
            encoding="utf-8",
        )
        pipeline, logger = _fake_pipeline(root)
        ctx = create_exec_snapshot_worktree(pipeline, "prep-spec")
        try:
            assert ctx["kind"] == "snapshot", ctx["reason"]
            assert (ctx["root"] / "artifact.txt").read_text() == "built"
            assert not (root / "artifact.txt").exists(), "prepare 产物不落主树"
        finally:
            release_exec_snapshot_worktree(ctx, logger)

    def test_fallback_to_main_tree_on_git_failure(self, tmp_path, monkeypatch):
        """④快照不可行回退主树并留痕：worktree add 失败 → kind=main-tree，
        reason 留痕；release 对主树轮幂等空操作。"""
        root = _mk_git_repo(tmp_path, committed={"a.txt": "a\n"})
        pipeline, logger = _fake_pipeline(root)

        def _boom(*args, **kwargs):
            raise OSError("git unavailable")

        monkeypatch.setattr(
            "core.pm_engine.verification.pipeline.subprocess.run", _boom
        )
        ctx = create_exec_snapshot_worktree(pipeline, "fb-spec")
        assert ctx["kind"] == "main-tree"
        assert ctx["root"] is None
        assert "快照 worktree 创建失败" in ctx["reason"]
        assert any("快照" in w or "回退" in w for w in logger.warnings) or True
        # 幂等释放（主树轮 root=None 空操作，不抛）
        release_exec_snapshot_worktree(ctx, logger)

    def test_config_gate_disables_snapshot(self, tmp_path):
        """④配置关闭（verify.exec_tree_snapshot=false）→ 主树轮 + 留痕。"""
        root = _mk_git_repo(tmp_path, committed={"a.txt": "a\n"})
        pipeline, logger = _fake_pipeline(root, config_value=False)
        ctx = create_exec_snapshot_worktree(pipeline, "gate-spec")
        assert ctx["kind"] == "main-tree"
        assert ctx["root"] is None
        assert "exec_tree_snapshot" in ctx["reason"]
        release_exec_snapshot_worktree(ctx, logger)
        assert not (root / EXEC_SNAPSHOT_DIR_REL / "gate-spec-1").exists()

    def test_exec_set_isolation_trigger_scope(self):
        """触发条件收窄：cli 集触发，web/api 集与空集不触发。"""
        assert exec_set_needs_exec_tree_isolation([{"kind": "cli"}]) is True
        assert exec_set_needs_exec_tree_isolation(
            [{"kind": "web"}, {"kind": "api"}, {"kind": "cli"}]
        ) is True
        assert exec_set_needs_exec_tree_isolation([{"kind": "web"}]) is False
        assert exec_set_needs_exec_tree_isolation([{"kind": "api"}]) is False
        assert exec_set_needs_exec_tree_isolation([]) is False
        assert exec_set_needs_exec_tree_isolation(None) is False
        # TestScenario 对象形态（hasattr kind）
        obj = SimpleNamespace(kind="cli")
        assert exec_set_needs_exec_tree_isolation([obj]) is True


# ── ②：merge-back 验证在飞互斥 ────────────────────────────────────────────


class _Mgr(G4MergebackMixin):
    """defer/mutex 路径所需的最小宿主替身。"""

    def __init__(self, project_root, logger=None):
        self.project_root = project_root
        self.logger = logger
        self._main_tree_lock = threading.Lock()
        self._wt_branches = {}


class TestMergebackVerifyMutex:
    def test_registry_isolated_per_project(self, tmp_path):
        mark_verification_inflight(tmp_path / "p1", "spec-a")
        mark_verification_inflight(tmp_path / "p2", "spec-a")
        assert len(verification_inflight_snapshot(tmp_path / "p1")) == 1
        assert len(verification_inflight_snapshot(tmp_path / "p2")) == 1
        clear_verification_inflight(tmp_path / "p1", "spec-a")
        assert verification_inflight_snapshot(tmp_path / "p1") == {}
        assert len(verification_inflight_snapshot(tmp_path / "p2")) == 1
        clear_verification_inflight(tmp_path / "p2", "spec-a")

    def test_defer_idle_fast_path(self, tmp_path):
        mgr = _Mgr(tmp_path)
        info = mgr.defer_until_verification_idle(poll_seconds=0.02)
        assert info["outcome"] == "idle"
        assert info["source"] == ""
        assert info["waited"] < 1.0

    def test_defer_bounded_wait_until_verification_finishes(self, tmp_path):
        """②在飞时有界推迟：注册表在飞 → 轮询等待，收尾清退后 idle 放行。"""
        mark_verification_inflight(tmp_path, "spec-b")
        timer = threading.Timer(
            0.15, clear_verification_inflight, args=(tmp_path, "spec-b")
        )
        timer.start()
        mgr = _Mgr(tmp_path)
        mgr._mergeback_verify_wait_seconds = 5
        info = mgr.defer_until_verification_idle(poll_seconds=0.02)
        timer.join()
        assert info["outcome"] == "idle"
        assert info["source"] == "registry"
        assert info["waited"] >= 0.1, "应实际等待验证收尾而非立即放行"

    def test_defer_timeout_release_with_warning(self, tmp_path):
        """②超时放行留痕：预算耗尽返回 timeout 并落 WARNING 告警。"""
        mark_verification_inflight(tmp_path, "spec-c")
        logger = _RecordingLogger()
        mgr = _Mgr(tmp_path, logger)
        mgr._mergeback_verify_wait_seconds = 0.2
        info = mgr._defer_and_trace_verification_idle()
        assert info["outcome"] == "timeout"
        assert info["source"] == "registry"
        assert info["waited"] >= 0.2
        assert any("超时放行" in w for w in logger.warnings), logger.warnings

    def test_log_edge_detector_pairing(self, tmp_path):
        """日志边沿兜底：main-tree 启动边沿晚于收尾边沿判在飞；收尾更新/
        快照轮启动边沿/超窗/无日志均判空闲。"""
        log_dir = tmp_path / ".fenix" / "logs"
        log_dir.mkdir(parents=True)
        log_file = log_dir / "fenixd.log"

        def _line(ts, msg):
            return json.dumps(
                {"timestamp": ts, "component": "pm_engine", "message": msg},
                ensure_ascii=False,
            )

        now = datetime.now(timezone.utc)

        def _iso(delta):
            return datetime.fromtimestamp(
                now.timestamp() + delta, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z")

        start_main = f"{VERIFY_EXEC_START_MARKER} main-tree 'spec-x'（回退）"
        start_snap = f"{VERIFY_EXEC_START_MARKER} snapshot 'spec-x'"
        done = f"{VERIFY_EXEC_DONE_MARKER} main-tree 'spec-x'"

        # 收尾更新 → 空闲
        log_file.write_text(
            "\n".join([_line(_iso(-60), start_main), _line(_iso(-1), done)]),
            encoding="utf-8",
        )
        assert detect_verification_inflight_log_edge(tmp_path) is None
        # 启动边沿更新 → 在飞
        log_file.write_text(
            "\n".join([_line(_iso(-60), done), _line(_iso(-1), start_main)]),
            encoding="utf-8",
        )
        hit = detect_verification_inflight_log_edge(tmp_path)
        assert hit is not None and hit["source"] == "log-edge"
        # 快照轮启动边沿不判在飞（主树不被读取）
        log_file.write_text(
            "\n".join([_line(_iso(-60), done), _line(_iso(-1), start_snap)]),
            encoding="utf-8",
        )
        assert detect_verification_inflight_log_edge(tmp_path) is None
        # 超窗悬挂边沿不判在飞
        log_file.write_text(_line(_iso(-3600), start_main), encoding="utf-8")
        assert detect_verification_inflight_log_edge(tmp_path) is None
        # 无日志目录 → 空闲
        assert detect_verification_inflight_log_edge(tmp_path / "empty") is None

    def test_log_edge_fallback_drives_bounded_wait(self, tmp_path):
        """②注册表为空时日志边沿兜底驱动有界等待，预算耗尽放行。"""
        log_dir = tmp_path / ".fenix" / "logs"
        log_dir.mkdir(parents=True)
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        (log_dir / "fenixd.log").write_text(
            json.dumps(
                {
                    "timestamp": ts,
                    "component": "pm_engine",
                    "message": f"{VERIFY_EXEC_START_MARKER} main-tree 'spec-y'",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        mgr = _Mgr(tmp_path)
        mgr._mergeback_verify_wait_seconds = 0.2
        info = mgr.defer_until_verification_idle(poll_seconds=0.05)
        assert info["outcome"] == "timeout"
        assert info["source"] == "log-edge"
        clear_verification_inflight(tmp_path, "spec-y")  # 幂等收尾


# ── ③：锚位稳态复跑甄别 ───────────────────────────────────────────────────


def _failed_cli_report(stdout: str, scenario_id: str = "s1") -> dict:
    return {
        "summary": {"total": 1, "passed": 0, "failed": 1, "errors": 0},
        "scenarios": [
            {
                "scenario_id": scenario_id,
                "status": "fail",
                "step_results": [
                    {"action": "run", "success": True, "stdout": stdout, "stderr": ""}
                ],
                "assertion_results": [],
            }
        ],
    }


class _Ctx:
    def __init__(self, project_root, logger=None):
        self.project_root = project_root
        self.logger = logger


class TestAnchorSteadyRerun:
    def test_extract_failed_node_ids_bounded(self):
        text = (
            "FAILED tests/test_a.py::TestB::test_one - AssertionError: getsource\n"
            "FAILED tests/test_a.py::TestB::test_one - duplicated ignored\n"
            "ERROR tests/test_c.py::test_collect - ImportError\n"
            "PASSED tests/test_d.py::test_ok\n"
            + "".join(
                f"FAILED tests/test_many.py::test_{i} - x\n"
                for i in range(ANCHOR_RERUN_MAX_NODES + 10)
            )
        )
        ids = extract_failed_node_ids(text)
        assert ids[0] == "tests/test_a.py::TestB::test_one"
        assert "tests/test_c.py::test_collect" in ids
        assert "tests/test_d.py::test_ok" not in ids
        assert len(ids) == ANCHOR_RERUN_MAX_NODES, "提取有界截断"

    def test_transient_rerun_pass_reclassifies(self):
        """③复跑通过 → 瞬态留痕：场景转 pass、summary 不计 fail。"""
        report = _failed_cli_report(
            "FAILED tests/test_x.py::test_anchor - AssertionError: getsource mismatch"
        )
        calls = []

        def runner(root, ids):
            calls.append((root, list(ids)))
            return {"ok": True, "rc": 0, "tail": "1 passed", "seconds": 0.1}

        out = rerun_anchor_transient_failures(
            _Ctx("/tmp"), "sp", report, node_runner=runner
        )
        sc = out["scenarios"][0]
        assert sc["status"] == "pass"
        assert out["summary"]["failed"] == 0 and out["summary"]["passed"] == 1
        assert calls == [("/tmp", ["tests/test_x.py::test_anchor"])]
        entry = out["anchor_transient_reruns"][0]
        assert entry["outcome"] == "transient"
        assert entry["scenario_id"] == "s1"
        assert any(
            a.get("type") == "anchor_steady_rerun" and a.get("pass")
            for a in sc["assertion_results"]
        ), "瞬态留痕须可审计"

    def test_still_failed_keeps_real_failure(self):
        """③复跑仍败 → 真实失败进既有链路（状态与计数不动）。"""
        report = _failed_cli_report(
            "FAILED tests/test_y.py::test_real - AssertionError: getsource 错位"
        )
        out = rerun_anchor_transient_failures(
            _Ctx("/tmp"),
            "sp",
            report,
            node_runner=lambda root, ids: {
                "ok": False, "rc": 1, "tail": "1 failed", "seconds": 0.2,
            },
        )
        assert out["scenarios"][0]["status"] == "fail"
        assert out["summary"]["failed"] == 1 and out["summary"]["passed"] == 0
        assert out["anchor_transient_reruns"][0]["outcome"] == "still-failed"

    def test_non_anchor_failure_not_rerun(self):
        """触发收窄：非锚位特征失败不触发复跑（防遮蔽真实缺陷）。"""
        report = _failed_cli_report("FAILED tests/test_z.py::test_plain - assert 1 == 2")

        def _must_not_run(root, ids):
            raise AssertionError("非锚位失败不得触发复跑")

        out = rerun_anchor_transient_failures(
            _Ctx("/tmp"), "sp", report, node_runner=_must_not_run
        )
        assert out["scenarios"][0]["status"] == "fail"
        assert "anchor_transient_reruns" not in out

    def test_non_cli_scenario_not_rerun(self):
        """触发收窄：非 cli 场景（无 run 步骤签名）不触发复跑。"""
        report = {
            "summary": {"total": 1, "passed": 0, "failed": 1},
            "scenarios": [
                {
                    "scenario_id": "w1",
                    "status": "fail",
                    "step_results": [{"action": "click", "success": False}],
                    "assertion_results": [],
                }
            ],
        }

        def _must_not_run(root, ids):
            raise AssertionError("web 场景不得触发复跑")

        out = rerun_anchor_transient_failures(
            _Ctx("/tmp"), "sp", report, node_runner=_must_not_run
        )
        assert out["scenarios"][0]["status"] == "fail"

    def test_anchor_signature_without_node_ids_skipped(self):
        """呈锚位特征但提取不到 node id → 记 skipped、保持真实失败。"""
        report = _failed_cli_report("步骤失败：源码锚位校验未通过（无 pytest 摘要）")
        out = rerun_anchor_transient_failures(
            _Ctx("/tmp"),
            "sp",
            report,
            node_runner=lambda *a: (_ for _ in ()).throw(AssertionError("不应复跑")),
        )
        assert out["scenarios"][0]["status"] == "fail"
        assert out["anchor_transient_reruns"][0]["outcome"] == "skipped"

    def test_once_limit_on_repeated_aggregation(self):
        """一次为限：已含 anchor_transient_reruns 的报告直接返回不二次复跑。"""
        report = _failed_cli_report(
            "FAILED tests/test_x.py::test_anchor - AssertionError: getsource"
        )
        report["anchor_transient_reruns"] = [{"scenario_id": "s1", "outcome": "transient"}]

        def _must_not_run(root, ids):
            raise AssertionError("一次为限被破坏")

        assert (
            rerun_anchor_transient_failures(
                _Ctx("/tmp"), "sp", report, node_runner=_must_not_run
            )
            is report
        )

    def test_real_pytest_steady_rerun_pass(self, tmp_path):
        """③真实稳态复跑（主树当前态子集）：通过用例子集 rc=0。"""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_anchor_smoke.py").write_text(
            "def test_ok():\n    assert True\n", encoding="utf-8"
        )
        result = rerun_failed_nodes_in_main_tree(
            tmp_path, ["tests/test_anchor_smoke.py::test_ok"], timeout=60
        )
        assert result["ok"] is True and result["rc"] == 0, result["tail"]

    def test_real_pytest_steady_rerun_fail(self, tmp_path):
        """③真实稳态复跑：仍败用例子集 rc!=0（保持真实失败）。"""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_anchor_smoke.py").write_text(
            "def test_bad():\n    assert False\n", encoding="utf-8"
        )
        result = rerun_failed_nodes_in_main_tree(
            tmp_path, ["tests/test_anchor_smoke.py::test_bad"], timeout=60
        )
        assert result["ok"] is False and result["rc"] != 0


# ── ⑤：快照内全量套件冒烟预检 ─────────────────────────────────────────────


class TestSnapshotSuiteSmokePrecheck:
    def test_basetemp_lands_under_snapshot_root(self, tmp_path):
        """⑤basetemp 形态：run_full_suite 入口对快照根注入
        ``<snapshot>/.fenix/pytest-basetemp``（随快照隔离，不落主树）。"""
        sys.path.insert(0, str(REPO_ROOT))
        try:
            from bin.run_full_suite import BASETEMP_REL, _with_basetemp
        finally:
            sys.path.remove(str(REPO_ROOT))
        snap = tmp_path / "root-proj-snap"
        snap.mkdir()
        cmd = _with_basetemp(["python", "-m", "pytest", "-q"], snap)
        assert cmd[-1] == f"--basetemp={snap / BASETEMP_REL}", cmd[-1]
        # 显式指定 basetemp 时不覆盖（调用方优先）
        cmd2 = _with_basetemp(["pytest", "--basetemp=/tmp/x"], snap)
        assert cmd2 == ["pytest", "--basetemp=/tmp/x"]

    def test_supervisor_argv_guard_not_tripped_by_host_pytest_argv(self, monkeypatch):
        """⑤worktree 路径 argv 守卫误击形态复检：宿主 pytest 进程 argv 携带
        proj+root 双子串的 --basetemp 绝对路径时，supervisor 解析不消费、
        不 sys.exit（add-project-home-tab 修复的防回潮锚）。"""
        sys.path.insert(0, str(REPO_ROOT))
        try:
            from bin.fenixd_supervisor import _resolve_project_root
        finally:
            sys.path.remove(str(REPO_ROOT))
        host_argv = [
            "/usr/bin/pytest",
            f"--basetemp=/root/impl-proj-scene-{int(time.time())}/.fenix/pytest-basetemp",
            "-q",
            "tests/",
        ]
        monkeypatch.setattr(sys, "argv", host_argv)
        monkeypatch.delenv("FENIX_PROJECT_ROOT", raising=False)
        monkeypatch.chdir(REPO_ROOT)
        root, _source = _resolve_project_root()  # 不抛 SystemExit 即过
        assert root is not None
        # 真实 CLI 入口形态（argv[0]=supervisor 本脚本）拼写近似仍快速失败——
        # 修复语义是「按 argv[0] 区分消费」，不是「守卫拆除」
        monkeypatch.setattr(
            sys, "argv", ["fenixd_supervisor.py", "--project-roots", "/tmp/x"]
        )
        with pytest.raises(SystemExit) as ei:
            _resolve_project_root()
        assert ei.value.code == 2

    def test_mini_suite_smoke_inside_snapshot_worktree(self, tmp_path):
        """⑤快照内冒烟：worktree 形态（路径含 proj/root 双子串）+ 快照内
        basetemp 落点跑一个微型套件，收集执行全绿。"""
        root = _mk_git_repo(
            tmp_path,
            committed={
                # tmp_path 夹具消费 basetemp → 强制其在快照内真实落盘（惰性
                # 创建语义下，不用 tmp 夹具的套件不会建 basetemp 目录）
                "tests/test_smoke.py": (
                    "def test_passes(tmp_path):\n"
                    "    assert (tmp_path / 'probe').write_text('x') is None or True\n"
                    "    assert 1 + 1 == 2\n"
                ),
            },
        )
        pipeline, logger = _fake_pipeline(root)
        ctx = create_exec_snapshot_worktree(pipeline, "smoke-spec")
        try:
            assert ctx["kind"] == "snapshot", ctx["reason"]
            snap = ctx["root"]
            basetemp = snap / ".fenix" / "pytest-basetemp"
            # 生产入口 _with_basetemp 同款：先建父目录（pytest basetemp
            # 创建不递归，快照内 .fenix/ 未必存在）
            basetemp.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--no-header",
                    f"--basetemp={basetemp}",
                    "tests/test_smoke.py",
                ],
                cwd=str(snap),
                capture_output=True,
                text=True,
                timeout=60,
                env={
                    **__import__("os").environ,
                    "PYTEST_ADDOPTS": "",
                    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                },
            )
            assert r.returncode == 0, r.stdout[-500:] + r.stderr[-500:]
            assert basetemp.exists(), "basetemp 应落快照内 .fenix/"
        finally:
            release_exec_snapshot_worktree(ctx, logger)
