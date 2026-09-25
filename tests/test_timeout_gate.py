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


class TestAllowlistSchema:
    """任务 2.3：豁免清单 schema 校验（真实清单必须干净；各类违规必须被指出）。"""

    @staticmethod
    def _violations_of(tmp_path, yaml_text):
        from conftest import load_timeout_allowlist, validate_timeout_allowlist

        path = tmp_path / "timeout-allowlist.yaml"
        path.write_text(yaml_text, encoding="utf-8")
        entries, error = load_timeout_allowlist(path)
        assert error is None, f"样例清单应可解析，却报错：{error}"
        return validate_timeout_allowlist(entries)

    def test_real_allowlist_is_clean(self):
        from conftest import load_timeout_allowlist, validate_timeout_allowlist

        entries, error = load_timeout_allowlist()
        assert error is None, f"仓库真实豁免清单不可解析：{error}"
        assert validate_timeout_allowlist(entries) == []

    def test_missing_or_blank_reason_is_flagged(self, tmp_path):
        violations = self._violations_of(
            tmp_path,
            textwrap.dedent(
                """\
                entries:
                  - nodeid: tests/test_x.py::test_no_reason
                    timeout_seconds: 30
                  - nodeid: tests/test_x.py::test_blank_reason
                    timeout_seconds: 30
                    reason: ""
                """
            ),
        )
        # 每条违规都要指出违规条目（序号 + 字段），reason 缺失与为空各计一条
        assert len(violations) == 2, violations
        assert "第 1 条" in violations[0] and "reason" in violations[0]
        assert "第 2 条" in violations[1] and "reason" in violations[1]

    def test_non_positive_timeout_seconds_is_flagged(self, tmp_path):
        violations = self._violations_of(
            tmp_path,
            textwrap.dedent(
                """\
                entries:
                  - nodeid: tests/test_x.py::test_zero
                    timeout_seconds: 0
                    reason: 零秒豁免
                  - nodeid: tests/test_x.py::test_negative
                    timeout_seconds: -5
                    reason: 负秒豁免
                """
            ),
        )
        assert len(violations) == 2, violations
        assert all("timeout_seconds" in v for v in violations)

    def test_missing_nodeid_is_flagged(self, tmp_path):
        violations = self._violations_of(
            tmp_path,
            textwrap.dedent(
                """\
                entries:
                  - timeout_seconds: 30
                    reason: 缺 nodeid
                """
            ),
        )
        assert len(violations) == 1, violations
        assert "nodeid" in violations[0]

    def test_malformed_yaml_is_flagged(self, tmp_path):
        from conftest import load_timeout_allowlist

        path = tmp_path / "broken.yaml"
        path.write_text("entries: [ {nodeid: a, timeout_seconds: 1", encoding="utf-8")
        entries, error = load_timeout_allowlist(path)
        assert entries == []
        assert error is not None and "解析失败" in error


# 内联同构 conftest（任务 2.4）：与 tests/conftest.py 的豁免注入钩子同构，
# 清单路径指向样例项目内的 timeout-allowlist.yaml——真实 conftest 的清单
# 路径指向仓库 tests/timeout-allowlist.yaml，pytester 临时项目命中不了。
SAMPLE_CONFTEST = textwrap.dedent(
    """\
    from pathlib import Path

    import pytest
    import yaml

    _ALLOWLIST = Path(__file__).resolve().parent / "timeout-allowlist.yaml"

    def pytest_collection_modifyitems(config, items):
        entries = []
        if _ALLOWLIST.exists():
            data = yaml.safe_load(_ALLOWLIST.read_text(encoding="utf-8")) or {}
            entries = data.get("entries") or []
        by_nodeid = {e["nodeid"]: e for e in entries}
        for item in items:
            entry = by_nodeid.get(item.nodeid)
            if entry is not None:
                item.add_marker(pytest.mark.timeout(entry["timeout_seconds"]))
    """
)


class TestAllowlistInjection:
    """任务 2.4：清单生效路径（内层默认阈值 1s，登记条目 2s，对照未登记条目）。"""

    def test_registered_entry_uses_registered_threshold(self, pytester):
        pytester.makefile(".ini", pytest=SAMPLE_INI)
        pytester.makeconftest(SAMPLE_CONFTEST)
        (pytester.path / "timeout-allowlist.yaml").write_text(
            textwrap.dedent(
                """\
                entries:
                  - nodeid: test_slow.py::test_registered_slow
                    timeout_seconds: 2
                    reason: 样例条目：验证登记阈值覆盖全局门
                """
            ),
            encoding="utf-8",
        )
        pytester.makepyfile(
            test_slow=textwrap.dedent(
                """\
                import time

                def test_registered_slow():
                    time.sleep(3)

                def test_unregistered_slow():
                    time.sleep(3)

                def test_fast():
                    assert True
                """
            )
        )
        # 内层默认阈值 1s：登记条目 2s（活过 1s 关口、2s 判超时）；
        # 对照未登记条目 1s 即超时；fast 用例不受影响。
        result = pytester.runpytest(
            "-o", "timeout=1", "-o", "timeout_method=signal", "test_slow.py",
        )
        result.assert_outcomes(failed=2, passed=1)
        # 登记条目：失败信息是 2s 关口（>1s 未杀 = 按登记阈值放行）
        result.stdout.fnmatch_lines(
            [
                "* test_registered_slow _*",
                f"*Timeout (>2*{TIMEOUT_MARKER}*",
            ]
        )
        # 对照：未登记条目 1s 即超时
        result.stdout.fnmatch_lines(
            [
                "* test_unregistered_slow _*",
                f"*Timeout (>1*{TIMEOUT_MARKER}*",
            ]
        )
