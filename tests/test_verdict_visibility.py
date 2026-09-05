"""fix-verify-verdict-visibility 测试：被裁决过滤失败场景的可见性。

覆盖：
- parse_filtered_failures 提取语义（test-defect 失败收录、product-bug 不收录、
  旧格式无 classification 不收录、evidence 多级回退、截图 basename 归一化）
- spec_detail 响应含 filtered_failures 新键
- agents/verifier.md 含出题选择器实测规则（MUST 措辞与 antd v6 反例）

隔离用户级配置（isolated_user_config 惯例）：data.py 的 read_effective_config
会合并用户级配置，本测试只触 parse/spec_detail 路径，仍统一 patch 防宿主机
环境敏感。
"""
import json
import tempfile
import unittest
from pathlib import Path

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _write_report(proot: Path, scenarios: list) -> None:
    """写 report.json 到 verify-progress/<spec>/。"""
    vp = proot / ".fenix" / "verify-progress" / "myspec"
    vp.mkdir(parents=True, exist_ok=True)
    (vp / "report.json").write_text(
        json.dumps({"summary": {"total": len(scenarios)},
                    "scenarios": scenarios}),
        encoding="utf-8",
    )


class TestParseFilteredFailures(unittest.TestCase):
    """parse_filtered_failures 提取语义。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir) / "proj"
        (self.proot / ".fenix").mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_test_defect_failure_collected(self):
        from core.dashboard.data import parse_filtered_failures
        _write_report(self.proot, [
            {"scenario_id": "s1", "status": "failed", "classification": "test-defect",
             "evidence": {"first_failed_step": "选择器在 antd v6 已改名"},
             "screenshots": ["/abs/fail1.png"], "status_corrected": True},
        ])
        res = parse_filtered_failures(self.proot, "myspec")
        assert len(res) == 1
        r = res[0]
        assert r["scenario_id"] == "s1"
        assert r["classification"] == "test-defect"
        assert r["evidence_summary"] == "选择器在 antd v6 已改名"
        assert r["screenshots"] == ["fail1.png"]  # basename 归一化
        assert r["status_corrected"] is True
        assert r["status"] == "failed"

    def test_product_bug_not_collected(self):
        from core.dashboard.data import parse_filtered_failures
        _write_report(self.proot, [
            {"scenario_id": "s1", "status": "failed", "classification": "product-bug",
             "evidence": {"first_failed_step": "真实缺陷"}},
            {"scenario_id": "s2", "status": "error", "classification": "test-defect"},
        ])
        res = parse_filtered_failures(self.proot, "myspec")
        assert [r["scenario_id"] for r in res] == ["s2"]

    def test_legacy_no_classification_not_collected(self):
        """旧格式 report.json 无 classification → fail-open 收录进 bugs，不进 filtered。"""
        from core.dashboard.data import parse_bugs, parse_filtered_failures
        _write_report(self.proot, [
            {"scenario_id": "s1", "status": "failed",
             "assertion_results": [{"type": "text_match", "pass": False,
                                    "message": "期望 '5' 实际 'x'"}]},
        ])
        filtered = parse_filtered_failures(self.proot, "myspec")
        bugs = parse_bugs(self.proot, "myspec")
        assert filtered == []
        # 旧格式场景按既有规则收录进 bugs，filtered 与 bugs 不双计
        assert [b["scenario_ids"] for b in bugs] == [["s1"]]

    def test_evidence_fallback_to_failed_assertion_actual(self):
        """evidence 无 first_failed_step → 回退 failed_assertions 首项 actual。"""
        from core.dashboard.data import parse_filtered_failures
        _write_report(self.proot, [
            {"scenario_id": "s1", "status": "fail", "classification": "env",
             "evidence": {"failed_assertions": [
                 {"type": "element_visible", "selector": ".foo", "actual": "超时未出现"}]}},
        ])
        res = parse_filtered_failures(self.proot, "myspec")
        assert res[0]["evidence_summary"] == "超时未出现"

    def test_evidence_empty_fallback_empty_string(self):
        """evidence 全缺 → evidence_summary 空串，不抛错。"""
        from core.dashboard.data import parse_filtered_failures
        _write_report(self.proot, [
            {"scenario_id": "s1", "status": "failed", "classification": "flaky"},
            {"scenario_id": "s2", "status": "failed", "classification": "env",
             "evidence": {"failed_assertions": []}},
        ])
        res = parse_filtered_failures(self.proot, "myspec")
        assert [r["evidence_summary"] for r in res] == ["", ""]

    def test_fail_failed_error_all_collected_pass_not(self):
        """status 枚举族（fail/failed/error）均收录；pass 不收录。"""
        from core.dashboard.data import parse_filtered_failures
        _write_report(self.proot, [
            {"scenario_id": "s1", "status": "fail", "classification": "env"},
            {"scenario_id": "s2", "status": "failed", "classification": "env"},
            {"scenario_id": "s3", "status": "error", "classification": "env"},
            {"scenario_id": "s4", "status": "pass", "classification": "test-defect"},
            {"scenario_id": "s5", "status": "warning", "classification": "env"},
        ])
        res = parse_filtered_failures(self.proot, "myspec")
        assert [r["scenario_id"] for r in res] == ["s1", "s2", "s3"]

    def test_missing_report_returns_empty(self):
        from core.dashboard.data import parse_filtered_failures
        assert parse_filtered_failures(self.proot, "ghost") == []


class TestSpecDetailFilteredFailures(unittest.TestCase):
    """spec_detail 响应新增 filtered_failures 键。"""

    def test_spec_detail_includes_filtered_failures(self):
        from core.dashboard.data import spec_detail
        tmpdir = tempfile.mkdtemp()
        try:
            proot = Path(tmpdir) / "proj"
            (proot / ".fenix" / "verify-progress" / "myspec").mkdir(parents=True)
            (proot / ".fenix" / "verify-progress" / "myspec" / "report.json").write_text(
                json.dumps({"scenarios": [
                    {"scenario_id": "s1", "status": "failed", "classification": "test-defect",
                     "evidence": {"first_failed_step": "antd v6 类名改名"},
                     "screenshots": ["/abs/ev.png"]},
                    {"scenario_id": "s2", "status": "failed", "classification": "product-bug",
                     "evidence": {"first_failed_step": "真实缺陷"}},
                ]}), encoding="utf-8")
            detail = spec_detail(proot, "myspec", {})
            assert "filtered_failures" in detail
            assert [r["scenario_id"] for r in detail["filtered_failures"]] == ["s1"]
            # bugs 互补收录 product-bug
            assert [b["scenario_ids"] for b in detail["bugs"]] == [["s2"]]
            # 与旧行为不回归：既有键仍在
            assert "bugs" in detail and "scenarios" in detail
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestVerifierSelectorEvidenceRule(unittest.TestCase):
    """agents/verifier.md 含出题选择器实测规则（MUST 措辞与 antd v6 反例）。"""

    def test_verifier_md_contains_selector_rule(self):
        verifier_path = Path(__file__).resolve().parent.parent / "agents" / "verifier.md"
        content = verifier_path.read_text(encoding="utf-8")
        assert "MUST" in content or "MANDATORY" in content
        # 「断言选择器必须来自实测 DOM / playwright 实查」语义的强制规则
        assert "playwright" in content
        assert "实测 DOM" in content
        # 「不得凭训练知识引用框架类名」约束
        assert "训练知识" in content
        assert "框架类名" in content
        # antd v6 反例说明
        assert ".ant-collapse-body" in content
        assert ".ant-collapse-panel" in content
        assert ".ant-collapse-content" in content
        # 反例与「已不存在」语义绑定
        assert "已不存在" in content


if __name__ == "__main__":
    unittest.main()
