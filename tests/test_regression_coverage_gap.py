"""prepare↔regression 一致性预检测试（evo-add-regression-coverage-guard）。

覆盖：半收编契约（prepare 有 pnpm --dir 条目、regression 无该包引用）→
发 regression_coverage_gap WARNING 且缺口清单含包名、加载不阻断（install
含尾随 flags 与 run build 两变体）；对称契约（cc-import/dashboard-bridge
形态）与纯 pytest 契约 → 零 WARNING、既有解析结果与校验违例集合零变化；
regression 段缺省（引导态合法形态）与非装配形态（--dir test）保守跳过。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.verify_contract import (
    FAIL_SERVE_INVALID,
    REGRESSION_COVERAGE_GAP_RULE_ID,
    RegressionSpec,
    load_verify_contract,
    validate_contract,
)


def _write(root: Path, rel: str, content: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# dsh-plugins 11-12 扩编实测形态：prepare 装配 SAS 插件、regression 只收编
# cc-import 与 dashboard-bridge（提案「扩编做一半」原型契约）。
HALF_ADOPTED = """
prepare:
  - run: pnpm --dir cc-import install --frozen-lockfile --prefer-offline
  - run: pnpm --dir dashboard-bridge install --frozen-lockfile --prefer-offline
  - run: pnpm --dir fenix-dsh-session-advanced-search install --frozen-lockfile --prefer-offline
serve:
  kind: static
  root: site
ready:
  url: /
  expect: 200
regression:
  cmd: "pnpm --dir cc-import test && pnpm --dir dashboard-bridge test --junit-xml=.fenix/regression/junit.xml"
  output: ".fenix/regression/junit.xml"
"""

# 对称形态：prepare 装配的每个包都在 regression cmd 中被引用。
SYMMETRIC = """
prepare:
  - run: pnpm --dir cc-import install --frozen-lockfile --prefer-offline
  - run: pnpm --dir dashboard-bridge run build
serve:
  kind: static
  root: site
ready:
  url: /
  expect: 200
regression:
  cmd: "pnpm --dir cc-import test && pnpm --dir dashboard-bridge test --junit-xml=.fenix/regression/junit.xml"
  output: ".fenix/regression/junit.xml"
"""

PURE_PYTEST = """
prepare:
  - run: touch built.txt
serve:
  kind: static
  root: site
ready:
  url: /
  expect: 200
regression:
  cmd: python3 -m pytest tests/ -q --junit-xml=.fenix/regression/junit.xml
  output: .fenix/regression/junit.xml
"""


class TestRegressionCoverageGap(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _load(self, text: str):
        _write(self.tmp, ".fenix/verify.yaml", text)
        logger = MagicMock()
        c = load_verify_contract(self.tmp, logger=logger)
        return c, logger

    def _warning_text(self, logger) -> str:
        return " || ".join(
            str(call.args) for call in logger.warning.call_args_list
        )

    # ── 3.1 半收编契约发出缺口告警 ──────────────────────────────────

    def test_half_adopted_contract_warns_with_package_name(self):
        """半收编契约：缺口清单含包名、带行号指引、加载不阻断。"""
        c, logger = self._load(HALF_ADOPTED)
        self.assertTrue(logger.warning.called)
        text = self._warning_text(logger)
        self.assertIn(REGRESSION_COVERAGE_GAP_RULE_ID, text)
        # 缺口清单含未收编包名
        self.assertIn("fenix-dsh-session-advanced-search", text)
        # 已收编包不进缺口清单
        self.assertNotIn("cc-import 缺口", text)
        self.assertNotIn("dashboard-bridge 缺口", text)
        # regression 段行号指引（regression: 位于文件第 12 行）
        self.assertIn("第 12 行", text)
        # 加载不阻断：契约对象完整、regression 正常解析
        self.assertIsNotNone(c)
        self.assertEqual(len(c.prepare), 3)
        self.assertIsInstance(c.regression, RegressionSpec)

    def test_run_build_variant_gap_detected(self):
        """run build 变体装配的包同样进缺口清单。"""
        c, logger = self._load(
            """
prepare:
  - run: pnpm --dir fenix-dsh-session-advanced-search run build
serve:
  kind: static
  root: site
regression:
  cmd: "python3 -m pytest tests/ -q --junit-xml=.fenix/regression/junit.xml"
  output: ".fenix/regression/junit.xml"
"""
        )
        self.assertTrue(logger.warning.called)
        text = self._warning_text(logger)
        self.assertIn(REGRESSION_COVERAGE_GAP_RULE_ID, text)
        self.assertIn("fenix-dsh-session-advanced-search", text)
        self.assertIsNotNone(c)

    def test_warning_emitted_on_validate_path_too(self):
        """校验路径（validate_contract）同样发声，且既有违例集合零变化。

        serve 段结构非法（static 缺 root）→ prepare 整段跳过（快、确定性），
        校验违例仍为既有 FAIL_SERVE_INVALID——新预检不改变违例集合。
        """
        _write(
            self.tmp,
            ".fenix/verify.yaml",
            """
prepare:
  - run: pnpm --dir fenix-dsh-session-advanced-search install --frozen-lockfile
serve:
  kind: static
regression:
  cmd: "python3 -m pytest tests/ -q --junit-xml=.fenix/regression/junit.xml"
  output: ".fenix/regression/junit.xml"
""",
        )
        logger = MagicMock()
        result = validate_contract(self.tmp, logger=logger)
        text = self._warning_text(logger)
        self.assertIn(REGRESSION_COVERAGE_GAP_RULE_ID, text)
        self.assertIn("fenix-dsh-session-advanced-search", text)
        # 既有校验结果零变化
        self.assertFalse(result.valid)
        self.assertEqual(result.fail_kind, FAIL_SERVE_INVALID)

    # ── 3.2 对称契约 / 纯 pytest 契约零输出 ─────────────────────────

    def test_symmetric_contract_silent(self):
        """对称契约（cc-import/dashboard-bridge 形态）：零 WARNING。"""
        c, logger = self._load(SYMMETRIC)
        self.assertFalse(logger.warning.called)
        # 既有解析结果零变化
        self.assertEqual(len(c.prepare), 2)
        self.assertEqual(c.serve.kind, "static")
        self.assertIsInstance(c.regression, RegressionSpec)
        self.assertIn("cc-import", c.regression.cmd)
        self.assertIn("dashboard-bridge", c.regression.cmd)

    def test_symmetric_contract_argv_list_cmd_silent(self):
        """regression cmd 为 argv 列表形态时对称判定同样成立。"""
        c, logger = self._load(
            """
prepare:
  - run: pnpm --dir cc-import install --frozen-lockfile
regression:
  cmd: ["pnpm", "--dir", "cc-import", "test"]
  output: ".fenix/regression/junit.xml"
"""
        )
        self.assertFalse(logger.warning.called)
        self.assertIsInstance(c.regression, RegressionSpec)

    def test_pure_pytest_contract_silent(self):
        """纯 pytest 契约（无 --dir 包形态）：保守跳过、零 WARNING。"""
        c, logger = self._load(PURE_PYTEST)
        self.assertFalse(logger.warning.called)
        self.assertEqual(len(c.prepare), 1)
        self.assertEqual(c.prepare[0].run, "touch built.txt")
        self.assertEqual(
            c.regression.cmd,
            "python3 -m pytest tests/ -q --junit-xml=.fenix/regression/junit.xml",
        )

    def test_regression_section_absent_conservative_skip(self):
        """regression 段缺省（引导态合法形态）：即使 prepare 装配包也跳过。"""
        c, logger = self._load(
            """
prepare:
  - run: pnpm --dir fenix-dsh-session-advanced-search install --frozen-lockfile
serve:
  kind: static
  root: site
"""
        )
        self.assertFalse(logger.warning.called)
        self.assertIsNone(c.regression)

    def test_regression_section_invalid_conservative_skip(self):
        """regression 段整段无效（缺 cmd）：既有 WARNING 之外不叠加缺口告警。"""
        _write(
            self.tmp,
            ".fenix/verify.yaml",
            """
prepare:
  - run: pnpm --dir fenix-dsh-session-advanced-search install --frozen-lockfile
regression:
  output: ".fenix/regression/junit.xml"
""",
        )
        logger = MagicMock()
        c = load_verify_contract(self.tmp, logger=logger)
        self.assertIsNone(c.regression)
        text = self._warning_text(logger)
        self.assertNotIn(REGRESSION_COVERAGE_GAP_RULE_ID, text)
        # 既有「缺 cmd」WARNING 保留
        self.assertIn("cmd", text)

    def test_non_install_build_variant_skipped(self):
        """--dir 后非 install/run build（如 test）：非装配形态，不取。"""
        _, logger = self._load(
            """
prepare:
  - run: pnpm --dir fenix-dsh-session-advanced-search test
serve:
  kind: static
  root: site
regression:
  cmd: "python3 -m pytest tests/ -q --junit-xml=.fenix/regression/junit.xml"
  output: ".fenix/regression/junit.xml"
"""
        )
        self.assertFalse(logger.warning.called)

    def test_root_dir_ref_excluded(self):
        """--dir .（根目录）不进包目录集：回归 cmd 天然含 "." 段，防反向误判。"""
        _, logger = self._load(
            """
prepare:
  - run: pnpm --dir . install --frozen-lockfile
serve:
  kind: static
  root: site
regression:
  cmd: "python3 -m pytest tests/ -q --junit-xml=.fenix/regression/junit.xml"
  output: ".fenix/regression/junit.xml"
"""
        )
        self.assertFalse(logger.warning.called)


if __name__ == "__main__":
    unittest.main()
