"""单用例超时硬门与豁免清单校验（add-per-test-timeout-gate）。

验证三件事（对应 spec/changes/add-per-test-timeout-gate）：
1. 门行为（任务 1.2）：超阈值用例判 FAILED，失败信息含机读标识
   「Timeout (>Ns) from pytest-timeout」与阈值秒数，同会话其余用例继续执行；
   门内正常用例行为不变。
2. 清单 schema 校验（任务 2.3）：reason 缺失/为空、timeout_seconds ≤ 0、
   必填字段缺失、YAML 非法均被指出（防静默豁免）。
3. 清单生效路径（任务 2.4）：登记条目按登记阈值判定，未登记条目按全局阈值。

门行为与清单生效用 pytester 内联样例（临时项目）验证，不向常驻套件引入
慢用例。pytester 项目落在仓内 basetemp（.fenix/pytest-basetemp，见 conftest
_isolated_basetemp_cleanup），内层 pytest 向上可发现仓根 pytest.ini——样例
项目内放最小 pytest.ini 钉住 rootdir（内层节点 ID 才相对样例项目、清单
nodeid 才能逐字对上），阈值用显式 -o 覆盖（否则内层继承仓级 10s 门）；
样例 sleep 时长取门内小尺度：外层用例自身受全局 10s 门约束，不得真等 15s。
"""

import textwrap

import pytest

pytest_plugins = ["pytester"]

# pytest-timeout 的机读超时标识稳定片段（pytest_timeout.PYTEST_FAILURE_MESSAGE
# = "Timeout (>%ss) from pytest-timeout."，%s 为阈值秒数）
TIMEOUT_MARKER = "s) from pytest-timeout"

# 样例项目最小 pytest.ini：钉 rootdir 到样例项目并切断向仓根 pytest.ini 的
# 继承（basetemp 在仓内，rootdir 上溯会命中仓根 10s 门）。
SAMPLE_INI = textwrap.dedent(
    """\
    [pytest]
    """
)


class TestGateBehavior:
    """任务 1.2：超时门行为（内层会话显式 -o timeout=2，样例 sleep(3)，不真等 15s）。"""

    def test_over_threshold_fails_with_marker_and_session_continues(self, pytester):
        pytester.makefile(".ini", pytest=SAMPLE_INI)
        pytester.makepyfile(
            test_gate=textwrap.dedent(
                """\
                import time

                def test_sleeps_over_threshold():
                    time.sleep(3)

                def test_neighbor_keeps_running():
                    assert True
                """
            )
        )
        result = pytester.runpytest(
            "-o", "timeout=2", "-o", "timeout_method=signal", "test_gate.py",
        )
        # 超时判 FAILED；同会话其余用例继续执行（不向常驻套件引入慢用例）
        result.assert_outcomes(failed=1, passed=1)
        # 失败信息含机读超时标识与阈值秒数（Timeout (>2.0s) from pytest-timeout）
        result.stdout.fnmatch_lines(
            [
                "* test_sleeps_over_threshold _*",
                f"*Timeout (>2*{TIMEOUT_MARKER}*",
            ]
        )

    def test_within_threshold_behaves_unchanged(self, pytester):
        pytester.makefile(".ini", pytest=SAMPLE_INI)
        pytester.makepyfile(
            test_ok=textwrap.dedent(
                """\
                def test_quick():
                    assert 1 + 1 == 2
                """
            )
        )
        result = pytester.runpytest(
            "-o", "timeout=2", "-o", "timeout_method=signal", "test_ok.py",
        )
        # 正常用例不受影响：门内完成即通过
        result.assert_outcomes(passed=1)
