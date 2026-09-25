"""verify.yaml regression 段解析测试（test-regression-declaration 能力）。

覆盖：有效段解析（含显式 timeout/threshold）、缺省阈值 8 / 缺省超时 1800、
无 regression 段 → None、无效段（缺 cmd/output、format 非 junit）→ None +
WARNING、非法数值回退缺省（task 1.3）。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.verify_contract import (
    RegressionSpec,
    load_verify_contract,
)

BASE_CONTRACT = """
prepare:
  - run: touch built.txt
serve:
  kind: static
  root: site
ready:
  url: /
  expect: 200
"""

REGRESSION_VALID = """
regression:
  cmd: "pytest --junit-xml=.fenix/regression/junit.xml"
  output: ".fenix/regression/junit.xml"
"""


def _write(root: Path, rel: str, content: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class TestRegressionContract(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_valid_regression_parsed(self):
        """有效段：cmd/output/缺省阈值 10/缺省超时 1800、format junit。"""
        _write(
            self.tmp,
            ".fenix/verify.yaml",
            BASE_CONTRACT + REGRESSION_VALID,
        )
        c = load_verify_contract(self.tmp)
        self.assertIsNotNone(c)
        self.assertIsInstance(c.regression, RegressionSpec)
        self.assertEqual(
            c.regression.cmd, "pytest --junit-xml=.fenix/regression/junit.xml"
        )
        self.assertEqual(c.regression.output, ".fenix/regression/junit.xml")
        self.assertEqual(c.regression.timeout_seconds, 1800)
        self.assertEqual(c.regression.format, "junit")
        self.assertEqual(c.regression.long_test_threshold_seconds, 8)
        # 既有字段不受影响（加法兼容）
        self.assertEqual(len(c.prepare), 1)
        self.assertEqual(c.serve.kind, "static")

    def test_explicit_timeout_and_threshold(self):
        """显式 timeout_seconds / long_test_threshold_seconds 按值解析。"""
        _write(
            self.tmp,
            ".fenix/verify.yaml",
            BASE_CONTRACT
            + """
regression:
  cmd: "go test"
  output: "junit.xml"
  timeout_seconds: 900
  long_test_threshold_seconds: 5
""",
        )
        c = load_verify_contract(self.tmp)
        self.assertEqual(c.regression.timeout_seconds, 900)
        self.assertEqual(c.regression.long_test_threshold_seconds, 5)

    def test_argv_list_cmd_supported(self):
        """cmd 可为 argv 列表（shell 字符串 / 列表两态）。"""
        _write(
            self.tmp,
            ".fenix/verify.yaml",
            BASE_CONTRACT
            + """
regression:
  cmd: ["pytest", "--junit-xml=junit.xml"]
  output: "junit.xml"
""",
        )
        c = load_verify_contract(self.tmp)
        self.assertEqual(c.regression.cmd, ["pytest", "--junit-xml=junit.xml"])
        self.assertEqual(c.regression.output, "junit.xml")

    def test_missing_section_returns_none(self):
        """无 regression 段 → None（未配置回归，零迁移）。"""
        _write(self.tmp, ".fenix/verify.yaml", BASE_CONTRACT)
        c = load_verify_contract(self.tmp)
        self.assertIsNotNone(c)
        self.assertIsNone(c.regression)

    def test_missing_cmd_invalid_with_warning(self):
        """缺 cmd：整段无效 → None + WARNING。"""
        _write(
            self.tmp,
            ".fenix/verify.yaml",
            BASE_CONTRACT
            + """
regression:
  output: "junit.xml"
""",
        )
        logger = MagicMock()
        c = load_verify_contract(self.tmp, logger=logger)
        self.assertIsNone(c.regression)
        self.assertTrue(logger.warning.called)
        self.assertIn("regression", str(logger.warning.call_args))
        self.assertIn("cmd", str(logger.warning.call_args))

    def test_missing_output_invalid_with_warning(self):
        """缺 output：整段无效 → None + WARNING。"""
        _write(
            self.tmp,
            ".fenix/verify.yaml",
            BASE_CONTRACT
            + """
regression:
  cmd: "pytest --junit-xml=junit.xml"
""",
        )
        logger = MagicMock()
        c = load_verify_contract(self.tmp, logger=logger)
        self.assertIsNone(c.regression)
        self.assertTrue(logger.warning.called)
        self.assertIn("output", str(logger.warning.call_args))

    def test_format_non_junit_invalid_with_warning(self):
        """format 声明为其它值（如 json）：整段无效 → None + WARNING（design D2）。"""
        _write(
            self.tmp,
            ".fenix/verify.yaml",
            BASE_CONTRACT
            + """
regression:
  cmd: "pytest --junit-xml=junit.xml"
  output: "junit.xml"
  format: json
""",
        )
        logger = MagicMock()
        c = load_verify_contract(self.tmp, logger=logger)
        self.assertIsNone(c.regression)
        self.assertTrue(logger.warning.called)
        self.assertIn("junit", str(logger.warning.call_args))

    def test_invalid_numeric_values_fall_back(self):
        """非法数值（非正数/类型错误）回退缺省（task 1.3）。"""
        for bad_timeout, bad_threshold, exp_t, exp_th in [
            (0, 0, 1800, 8),
            (-5, -1, 1800, 8),
            ("abc", "x", 1800, 8),
            (True, False, 1800, 8),  # bool 是 int 子类，显式排除
        ]:
            with self.subTest(bad_timeout=bad_timeout, bad_threshold=bad_threshold):
                _write(
                    self.tmp,
                    ".fenix/verify.yaml",
                    BASE_CONTRACT
                    + f"""
regression:
  cmd: "pytest --junit-xml=junit.xml"
  output: "junit.xml"
  timeout_seconds: {bad_timeout}
  long_test_threshold_seconds: {bad_threshold}
""",
                )
                c = load_verify_contract(self.tmp)
                self.assertIsNotNone(c.regression)
                self.assertEqual(c.regression.timeout_seconds, exp_t)
                self.assertEqual(c.regression.long_test_threshold_seconds, exp_th)

    def test_invalid_section_type_returns_none(self):
        """regression 段非映射（如字符串）→ None + WARNING。"""
        _write(
            self.tmp,
            ".fenix/verify.yaml",
            BASE_CONTRACT + "\nregression: just-a-string\n",
        )
        logger = MagicMock()
        c = load_verify_contract(self.tmp, logger=logger)
        self.assertIsNone(c.regression)
        self.assertTrue(logger.warning.called)


if __name__ == "__main__":
    unittest.main()