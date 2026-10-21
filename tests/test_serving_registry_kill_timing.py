"""test_serving_registry_kill_timing.py — 双 kill_process_group 实现时序守卫。

code-review item 54999e264b85：core.serving_registry.kill_process_group 与
core.proc_utils.kill_process_group 构成并行的两套实现（句柄形态不同，未
并入单点），时序常量此前仅靠注释纪律防漂移——任一侧单独调整等待时长或
升级信号序列，会造成同名函数语义静默分叉。本守卫把两侧取值与升级序列钉住，
任一侧漂移即失败，提示两侧同步修订。

纯静态断言（模块常量 + inspect.getsource），不启动真实进程、不发送任何
信号，离线可跑。
"""

import inspect

import core.proc_utils as proc_utils
import core.serving_registry as serving_registry

# 双实现（模块, 函数名）清单
_BOTH_IMPLS = [
    (serving_registry, "kill_process_group"),
    (proc_utils, "kill_process_group"),
]


def test_timing_constants_pinned():
    """两侧时序常量取值钉死：serving_registry 固定 3 秒 / proc_utils 默认 5 秒。"""
    assert serving_registry.KILL_WAIT_SECONDS == 3
    assert proc_utils.TERM_GRACE_SECONDS == 5
    # proc_utils.kill_process_group 的缺省 term_grace 须绑定共享常量
    # （单侧把缺省改回裸字面量而漏改常量，同样在此失败）
    default = inspect.signature(proc_utils.kill_process_group).parameters[
        "term_grace"
    ].default
    assert default == proc_utils.TERM_GRACE_SECONDS


def test_serving_registry_wait_uses_shared_constant():
    """serving_registry 侧的升级等待取自 KILL_WAIT_SECONDS（非裸 3.0 死值）。"""
    src = inspect.getsource(serving_registry.kill_process_group)
    assert "KILL_WAIT_SECONDS" in src


def test_escalation_sequence_sigterm_before_sigkill():
    """两实现均为 SIGTERM → 等待 → SIGKILL 升级序列（SIGKILL 不先于 SIGTERM）。"""
    for mod, name in _BOTH_IMPLS:
        src = inspect.getsource(getattr(mod, name))
        assert "signal.SIGTERM" in src, f"{mod.__name__}.{name} 缺 SIGTERM 段"
        assert "signal.SIGKILL" in src, f"{mod.__name__}.{name} 缺 SIGKILL 兜底"
        assert src.index("signal.SIGTERM") < src.index("signal.SIGKILL"), (
            f"{mod.__name__}.{name} 升级序列漂移：SIGKILL 先于 SIGTERM"
        )
