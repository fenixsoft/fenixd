"""basetemp 会话隔离契约守卫（2026-11-21 全量回归批量 setup 假失败防回潮）。

根因：裸 pytest 会话的兜底 basetemp 共用无后缀共享根
``<root>/.fenix/pytest-basetemp``，并发会话一方收尾 ``rmtree`` 连根拔掉
另一方在飞的 tmp 树，幸存方 ``TempPathFactory._basetemp`` 缓存不重建，
后续全部 ``tmp_path`` 用例 setup 报 ENOENT（单轮回归 907 例假失败）。
修复：兜底根改 pid 唯一（``pytest-basetemp-<pid>``——无锁保护面互不交叉，
宁可留残根也不互删）＋ setup 顺带清扫死进程残根；run_full_suite 主机锁
失效回退（``unique=True``）同形态。

本守卫把三条契约钉死，防修复回潮：
1. 兜底根模板必须 pid 唯一，且仅在未给定 ``--basetemp`` 时生效；
2. 残根清扫只删「名字带 pid 后缀且 pid 已死」的根——裸共享根（锁保护面）
   与活进程根 MUST NOT 触碰；
3. run_full_suite 锁回退注入的也是 pid 唯一根，且不覆盖调用方显式指定。
"""

import os
import subprocess
import sys
from pathlib import Path

from tests.conftest import _sweep_dead_basetemp_roots

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
