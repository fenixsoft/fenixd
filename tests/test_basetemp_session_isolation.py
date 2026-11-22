"""basetemp 会话隔离契约守卫（2026-11-21 全量回归批量 setup 假失败防回潮）。

根因：裸 pytest 会话的兜底 basetemp 共用无后缀共享根
``<root>/.fenix/pytest-basetemp``，并发会话一方收尾 ``rmtree`` 连根拔掉
另一方在飞的 tmp 树，幸存方 ``TempPathFactory._basetemp`` 缓存不重建，
后续全部 ``tmp_path`` 用例 setup 报 ENOENT（单轮回归 907 例假失败）。
修复：兜底根改 pid 唯一（``pytest-basetemp-<pid>``——无锁保护面互不交叉，
宁可留残根也不互删）＋ setup 顺带清扫死进程残根；run_full_suite 主机锁
失效回退（``unique=True``）同形态。

本守卫把六条契约钉死，防修复回潮：
1. 兜底根模板必须 pid 唯一，且仅在未给定 ``--basetemp`` 时生效；
2. 残根清扫只删「名字带 pid 后缀且 pid 已死」的根——裸共享根（锁保护面）
   与活进程根 MUST NOT 触碰；
3. run_full_suite 锁回退注入的也是 pid 唯一根，且不覆盖调用方显式指定；
4. 会话收尾只 rmtree 自建根，调用方给定共享根不删（2026-11-22 事故删除源）；
5. 每用例生命线守卫能重建被中途拔掉的缓存根，且属性缺失/失败 fail-open；
6. 端到端重放：给定共享根在子会话中途被拔 → 余下用例全绿存活（契约 5 是
   单元级钉，本条经真实 pytest 子进程装配重放事故全形态）；
7. setup 阶段前置钩子层：生命线先于任何作用域夹具实例化（session/module
   级夹具先于函数级 autouse 守卫装配的缺口收口）。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from tests.conftest import _ensure_basetemp_alive, _sweep_dead_basetemp_roots

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFTEST = Path(__file__).resolve().parent / "conftest.py"


def _dead_pid() -> int:
    """产出一个确定已死且已回收的 pid：spawn ``true`` 并 wait 收尸。

    收尸后内核即回收该 pid，``os.kill(pid, 0)`` 抛 ProcessLookupError——
    与清扫器的存活探测口径一致（pid 复用窗口理论存在，实操可忽略）。
    """
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


class TestFallbackBasetempPidUnique:
    def test_fallback_root_template_is_pid_suffixed(self):
        """契约 1：裸会话兜底根 pid 唯一，且仅在未给定 --basetemp 时生效。

        静态守卫（防回潮锚）：共享无后缀根在并发裸会话下正是 2026-11-21
        事故形态，模板回退为无后缀即视为回归。
        """
        src = CONFTEST.read_text(encoding="utf-8")
        assert 'f"pytest-basetemp-{os.getpid()}"' in src
        # 兜底前置条件：given basetemp（run_full_suite 锁内注入）不得被覆盖
        assert "factory._given_basetemp is None" in src

    def test_sweep_only_removes_dead_pid_roots(self, tmp_path):
        """契约 2：清扫只删死 pid 残根；裸共享根与活进程根不得触碰。"""
        keep = tmp_path / f"pytest-basetemp-{os.getpid()}"
        plain = tmp_path / "pytest-basetemp"  # 锁保护面（全量套件注入），无后缀
        live = tmp_path / f"pytest-basetemp-{os.getppid()}"  # 活进程（pytest 父进程）
        dead = tmp_path / f"pytest-basetemp-{_dead_pid()}"
        unrelated = tmp_path / "not-a-basetemp-root"
        for d in (keep, plain, live, dead, unrelated):
            d.mkdir()
        _sweep_dead_basetemp_roots(tmp_path, keep=keep.name)
        assert not dead.exists(), "死 pid 残根应被清扫回收"
        for d in (keep, plain, live, unrelated):
            assert d.exists(), f"{d.name} 不应被清扫"


class TestRunFullSuiteLockFallback:
    def test_unique_fallback_basetemp_is_pid_suffixed(self, tmp_path):
        """契约 3：主机锁回退（unique=True）注入 pid 唯一根，与裸会话兜底同形态。"""
        sys.path.insert(0, str(REPO_ROOT))
        try:
            from bin.run_full_suite import _with_basetemp
        finally:
            sys.path.remove(str(REPO_ROOT))
        cmd = _with_basetemp(["python", "-m", "pytest", "-q"], tmp_path, unique=True)
        assert cmd[-1].startswith("--basetemp=")
        base = Path(cmd[-1].split("=", 1)[1])
        assert base == tmp_path / ".fenix" / f"pytest-basetemp-{os.getpid()}"
        # 调用方已显式指定时不覆盖（调用方优先）
        cmd2 = _with_basetemp(["pytest", "--basetemp=/tmp/x"], tmp_path, unique=True)
        assert cmd2 == ["pytest", "--basetemp=/tmp/x"]


class TestSharedRootEndCleanupAndLiveness:
    def test_given_shared_root_not_removed_at_session_end(self):
        """契约 4：会话收尾只清自建根，调用方给定共享根（--basetemp）不 rmtree。

        同根无锁并发会话一方收尾连根拔掉另一方在飞 tmp 树，正是 2026-11-22
        全量回归 907 例批量 setup 假失败的删除源之一。静态钉：分流开关存在
        且以 given_by_caller 守卫收尾 rmtree。
        """
        src = CONFTEST.read_text(encoding="utf-8")
        assert "given_by_caller = factory._given_basetemp is not None" in src
        assert "if not given_by_caller:" in src

    def test_liveness_guard_rebuilds_deleted_root(self, tmp_path):
        """契约 5a：缓存根被中途拔掉 → 生命线重建（幸存方不再雪崩）。"""
        given = tmp_path / "pytest-basetemp"
        given.mkdir()
        factory = type("F", (), {"_basetemp": None, "_given_basetemp": given})()
        shutil.rmtree(given)
        _ensure_basetemp_alive(factory)
        assert given.is_dir(), "被拔的缓存根应被幂等重建"
        # 父链整体被拔时同样能重建（parents=True）
        deep = tmp_path / "lvl1" / "pytest-basetemp"
        factory2 = type("F", (), {"_basetemp": None, "_given_basetemp": deep})()
        _ensure_basetemp_alive(factory2)
        assert deep.is_dir()

    def test_liveness_guard_fail_open(self):
        """契约 5b：属性缺失/失败 fail-open，不为生命线本身引入新 setup 失败。"""
        _ensure_basetemp_alive(object())  # 两属性皆缺，不得抛
        _ensure_basetemp_alive(
            type("F", (), {"_basetemp": None, "_given_basetemp": None})()
        )  # 双 None 同静默
        # mkdir 失败（父为文件）同样吞掉
        from pathlib import Path as _P

        block = _P(__file__).parent / "_liveness_guard_blocker.tmp"
        block.write_text("x", encoding="utf-8")
        try:
            _ensure_basetemp_alive(
                type("F", (), {"_basetemp": block, "_given_basetemp": None})()
            )
        finally:
            block.unlink()


class TestSharedRootMidRunDeletionHeal:
    """契约 6：给定共享根中途被拔 → 子会话余下用例全绿（端到端重放）。

    2026-11-22 全量回归批量 setup 假失败的真实全形态：run_full_suite 注入的
    给定根（``--basetemp=<root>/.fenix/pytest-basetemp``）在会话进行中被外部
    连根拔掉（无锁并发会话收尾 rmtree、外部清理周期），幸存会话 ``_basetemp``
    缓存不重建，后续 ``tmp_path`` 用例 setup 在 ``make_numbered_dir`` 的
    ``find_suffixes(root)`` 处报 ``FileNotFoundError``（消息恰为裸根路径）。
    契约 5 钉的是生命线单元行为；本类经真实 pytest 子进程装配重放同一事故。
    """

    # 子会话用例：取回归失败台账同类快速 tmp_path 用例（0.9s/32 例实测），
    # 首例触发拔根、余下三例必须经生命线重建后存活。
    CHILD_NODEIDS = [
        "tests/test_review_circuit_breaker.py::TestClassifyRunFailure::test_infra_balance",
        "tests/test_review_circuit_breaker.py::TestClassifyRunFailure::test_infra_403",
        "tests/test_review_circuit_breaker.py::TestClassifyRunFailure::test_infra_429",
        "tests/test_review_circuit_breaker.py::TestClassifyRunFailure::test_content_normal",
    ]

    def test_given_root_deleted_midrun_session_survives(self, tmp_path):
        root = tmp_path / "pytest-basetemp"
        root.mkdir()
        marker = tmp_path / "deleted.marker"
        # 一次性插件（经 PYTHONPATH 注入、落在 tmp_path，不触仓库）：首个用例
        # teardown 后模拟外部清理者连根拔掉给定根，并落 marker 证明删除确已
        # 发生——防钉退化为永不触发的空转（拔根未发生时本用例无意义）。
        plugin = tmp_path / "kill_basetemp_after_first.py"
        plugin.write_text(
            "import os, pathlib, shutil\n"
            "_done = False\n"
            "def pytest_runtest_teardown(item, nextitem):\n"
            "    global _done\n"
            "    if _done:\n"
            "        return\n"
            "    _done = True\n"
            "    shutil.rmtree(os.environ['KILL_BASETEMP_ROOT'], ignore_errors=True)\n"
            "    pathlib.Path(os.environ['KILL_BASETEMP_MARKER']).write_text(\n"
            "        'deleted', encoding='utf-8')\n",
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "PYTHONPATH": str(tmp_path),
            "KILL_BASETEMP_ROOT": str(root),
            "KILL_BASETEMP_MARKER": str(marker),
        }
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             # PYTHONPATH 上的插件模块不会自动加载，必须 -p 显式激活
             "-p", "kill_basetemp_after_first",
             f"--basetemp={root}", *self.CHILD_NODEIDS],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=60,
        )
        assert marker.exists(), "插件未触发拔根，端到端重放未生效（钉已空转）"
        assert proc.returncode == 0, (
            f"给定根被中途拔掉后子会话应全绿存活（生命线重建失效）：\n"
            f"{proc.stdout[-2000:]}\n{proc.stderr[-500:]}"
        )


class TestLivenessGuardSetupHookLayer:
    def test_setup_phase_hook_precedes_all_scope_fixtures(self):
        """契约 7：生命线须有 setup 阶段前置钩子层，先于任何作用域夹具实例化。

        函数级 autouse 夹具只先于同作用域显式夹具；session/module 级夹具在
        它之前实例化——给定共享根恰在其首次装配前被拔除时，函数级守卫来不及
        重建，夹具内报 basetemp ENOENT 并级联拖垮该作用域全部用例。静态钉：
        conftest MUST 保留 tryfirst 的 ``pytest_runtest_setup`` 钩子调用
        ``_ensure_basetemp_alive``（丢失即视为更高作用域缺口回潮）。
        """
        src = CONFTEST.read_text(encoding="utf-8")
        assert "@pytest.hookimpl(tryfirst=True)" in src
        assert "def pytest_runtest_setup(item):" in src
        # 钩子体内调用生命线重建（截取该函数体，防无关同名钩子顶替）
        hook_body = src.split("def pytest_runtest_setup(item):", 1)[1].split(
            "\ndef ", 1
        )[0]
        assert "_ensure_basetemp_alive(" in hook_body
