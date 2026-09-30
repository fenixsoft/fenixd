"""tests/test_suite_lock_parity.py — code-review item 4d9161a8a090

core/regression.py 与 bin/run_full_suite.py 各自持有一份主机级锁常量
（锁路径 + 等待超时），注释仅声明「同值」而无单源约束；任一侧漂移即
两把锁指向不同文件，全量回归与 run_full_suite 的主机级互斥静默失效。
本测试钉死两份常量两两相等——锁路径或超时单侧变更时在此失败提醒，
须两侧同步修改。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bin.run_full_suite import LOCK_FILE_REL, LOCK_WAIT_TIMEOUT_SECONDS
from core import regression


class TestSuiteLockParity:
    """core/regression.py 与 bin/run_full_suite.py 主机级锁常量一致性。"""

    def test_lock_file_rel_parity(self):
        """锁路径两份定义必须同值，否则互斥指向不同文件而静默失效。"""
        assert regression._LOCK_FILE_REL == LOCK_FILE_REL

    def test_lock_wait_timeout_parity(self):
        """锁等待超时两份定义必须同值，否则两侧放弃/降级时机漂移。"""
        assert regression._LOCK_WAIT_TIMEOUT_SECONDS == LOCK_WAIT_TIMEOUT_SECONDS
