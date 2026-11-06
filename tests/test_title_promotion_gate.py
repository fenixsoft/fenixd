"""tests for add-spec-title-promotion-gate（title 存在性晋升硬门）.

Covers spec delta draft-promotion-gate「中文标题晋升硬门」：
- 缺 title 晋升被打回（drafted + error 既有形态 + 处方文案）
- 空 title 同判违规
- fix-cr-* 豁免（code-fix 程序化通道）
- 有 title 晋升零变化（不因长度/内容拦截）
- 补写后重晋升通过（自愈路径，30 分钟周期扫描重试的同型）
- D2/D4 边界：YAML 解析失败同判违规；fix-* 泛前缀不豁免
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine.promotion import promote_drafted
from core.state_machine import StateMachine


def _setup_project(tmpdir, spec_name="add-myspec", status="drafted",
                   spec_yaml=None):
    """最小可解析项目：.fenix/STATE.md + spec/changes/<name>/tasks.md。

    与 tests/test_pm_promotion_gate.py 的 _setup_project 同型（tasks.md 无
    Deliverables 段 → 声明 lint 返回空清单，晋升变量隔离在 title 门）。
    spec_yaml 非 None 时写入 .spec.yaml 内容，None 时保持文件缺失。
    """
    proot = Path(tmpdir)
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    state_path = proot / ".fenix" / "STATE.md"
    sm = StateMachine(state_path, MagicMock())
    sm.add_spec(spec_name, {"status": status})
    spec_dir = proot / "spec" / "changes" / spec_name
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "tasks.md").write_text(
        "## 1. 阶段一\n\n- [x] 1.1 任务一\n", encoding="utf-8"
    )
    if spec_yaml is not None:
        (spec_dir / ".spec.yaml").write_text(spec_yaml, encoding="utf-8")
    return proot, sm, state_path


def _promote(proot, sm, spec_name):
    return promote_drafted(proot, spec_name, state_machine=sm,
                           logger=MagicMock())


class TestTitlePromotionGate(unittest.TestCase):
    """promote_drafted title 存在性 lint：四场景 + 自愈。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_title_blocks_with_prescription(self):
        """缺 title → 晋升违规（drafted + error），消息含写入处方与规范出处。"""
        proot, sm, _ = _setup_project(self.tmpdir, spec_yaml=None)
        result = _promote(proot, sm, "add-myspec")
        self.assertFalse(result["ok"])
        self.assertTrue(result["error_written"])
        entry = sm.read_one("add-myspec")
        # drafted + error 既有形态（零新机制，D1）
        self.assertEqual(entry["status"], "drafted")
        error = entry.get("error") or ""
        # 处方：最小写入示例（追加 .spec.yaml 末行）
        self.assertIn("title: <5-25字中文标题>", error)
        self.assertIn(".spec.yaml", error)
        # 处方：规范出处（add-spec-chinese-title 生成纪律）
        self.assertIn("add-spec-chinese-title", error)
        # 违规前缀（与声明/tasks lint 同链组装形态）
        self.assertIn("中文标题存在性 lint 未通过", error)

    def test_blank_title_same_violation(self):
        """title 行存在但值空白（去首尾空后空串/None）→ 与缺失同判同处方。"""
        for spec_yaml in ("title:   \n", "title: ''\n"):
            with self.subTest(spec_yaml=spec_yaml):
                tmp = tempfile.mkdtemp()
                try:
                    proot, sm, _ = _setup_project(tmp, spec_yaml=spec_yaml)
                    result = _promote(proot, sm, "add-myspec")
                    self.assertFalse(result["ok"])
                    entry = sm.read_one("add-myspec")
                    self.assertEqual(entry["status"], "drafted")
                    self.assertIn("title: <5-25字中文标题>",
                                  entry.get("error") or "")
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)

    def test_yaml_parse_failure_blocks(self):
        """.spec.yaml YAML 解析失败 → 违规（D2 机械网 fail-closed）。"""
        proot, sm, _ = _setup_project(
            self.tmpdir, spec_yaml="title: [未闭合\n  bad yaml: :\n")
        result = _promote(proot, sm, "add-myspec")
        self.assertFalse(result["ok"])
        entry = sm.read_one("add-myspec")
        self.assertEqual(entry["status"], "drafted")
        self.assertIn("解析失败", entry.get("error") or "")

    def test_fix_cr_prefix_exempt(self):
        """fix-cr-* 前缀豁免先判：无 .spec.yaml 也照常晋升（D4 精确前缀）。"""
        proot, sm, _ = _setup_project(self.tmpdir, spec_name="fix-cr-1234-abcd",
                                      spec_yaml=None)
        result = _promote(proot, sm, "fix-cr-1234-abcd")
        # promote_drafted 为共享判定函数：ok=True 即可晋升，transition 由
        # 调用方（engine/CLI/Dashboard）执行（与 test_pm_promotion_gate
        # TestSharedPromotionFunction 同口径，status 断言不进本单元）
        self.assertTrue(result["ok"])
        self.assertEqual(result["violations"], [])

    def test_fix_generic_prefix_not_exempt(self):
        """fix-* 泛前缀不豁免（D4：手工 fix-* 与其他通道同等必填）。"""
        proot, sm, _ = _setup_project(self.tmpdir, spec_name="fix-my-thing",
                                      spec_yaml=None)
        result = _promote(proot, sm, "fix-my-thing")
        self.assertFalse(result["ok"])

    def test_non_empty_title_passes_unchanged(self):
        """有非空 title → 该检查通过，晋升零变化（不因长度/内容拦截）。"""
        proot, sm, _ = _setup_project(
            self.tmpdir,
            spec_yaml="schema: spec-driven\ncreated: 2026-11-06\n"
                      "mode: fast-track\ntitle: 短标题\n")
        result = _promote(proot, sm, "add-myspec")
        self.assertTrue(result["ok"])
        self.assertEqual(result["violations"], [])
        self.assertEqual(result["next_status"], "ready")

    def test_title_self_heal_repromote_passes(self):
        """自愈路径：违规打回 → 补写 title 一行 → 周期重试晋升通过。"""
        proot, sm, _ = _setup_project(self.tmpdir, spec_yaml=None)
        first = _promote(proot, sm, "add-myspec")
        self.assertFalse(first["ok"])
        self.assertTrue(first["error_written"])
        self.assertEqual(sm.read_one("add-myspec")["status"], "drafted")

        # 立项方按处方补写一行（追加 .spec.yaml 末行）
        spec_dir = proot / "spec" / "changes" / "add-myspec"
        (spec_dir / ".spec.yaml").write_text("title: 演示中文标题\n",
                                             encoding="utf-8")
        second = _promote(proot, sm, "add-myspec")
        self.assertTrue(second["ok"])
        self.assertEqual(second["violations"], [])


if __name__ == "__main__":
    unittest.main()
