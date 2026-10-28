"""tests/test_admin_prompt_choice_payload_contract.py — administrator prompt
载荷契约钉死测试（fix-admin-choice-payload-and-scenario-pairing 5.1）。

断言 agents/administrator.md 的「裁决选项消费契约」段含 choice_payload 载荷
路径规则（场景/夹具修订 MUST 经载荷路径、MUST NOT out-of-band 直接手改）、
成对写回理由与处置记录模板 choice_payload 键——防后续 prompt 改写静默丢失
契约（契约是 2026-10-28 add-merged-branch-gc 停车事故的结构性修复之一，
丢失即载荷通道对 Administrator 重新不可见）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ADMIN_MD = Path(__file__).resolve().parents[1] / "agents" / "administrator.md"


def _contract_text() -> str:
    return _ADMIN_MD.read_text(encoding="utf-8")


def _contract_section(text: str) -> str:
    """截取「裁决选项消费契约」段（起于标题，止于下一个二级标题）。"""
    start = text.index("## 裁决选项消费契约")
    nxt = text.find("\n## ", start + 1)
    return text[start:nxt if nxt != -1 else len(text)]


class TestAdminPromptChoicePayloadContract:
    def test_contract_section_mentions_choice_payload(self):
        text = _contract_section(_contract_text())
        assert "choice_payload" in text, (
            "裁决选项消费契约段丢失 choice_payload 载荷路径规则")

    def test_contract_names_revise_scenario_reverify_channel(self):
        text = _contract_section(_contract_text())
        assert "revise_scenario_reverify" in text
        assert '"choice_id": "revise_scenario_reverify"' in text, (
            "契约须写明载荷经 revise_scenario_reverify 选项提交的通道形态")

    def test_contract_payload_shape(self):
        text = _contract_section(_contract_text())
        # 契约形态：完整场景集 JSON {"scenarios": [...], "reason": ..., "fixture_files": [...]}
        assert '"scenarios"' in text
        assert '"reason"' in text
        assert '"fixture_files"' in text

    def test_contract_forbids_out_of_band_editing(self):
        text = _contract_section(_contract_text())
        assert "MUST NOT" in text
        assert "直接编辑" in text or "手改" in text, (
            "契约须含「MUST NOT 绕开执行器直接编辑/手改场景定义与夹具文件」"
            "的明文约束")
        # 禁止对象覆盖三类文件（场景定义 / 全量备份 / 夹具供给层）
        assert "test_scenarios.json" in text
        assert "_scenarios_full.json" in text
        assert "夹具" in text

    def test_contract_states_pair_consistency_rationale(self):
        text = _contract_section(_contract_text())
        # 理由说明：单独手改单侧文件破坏成对一致，旧定义经「无理由缺场景
        # 补齐」分支回填复辟
        assert "成对" in text, "契约须说明成对写回与配对一致理由"
        assert "回填复辟" in text, (
            "契约须说明旧定义可经「无理由缺场景补齐」分支回填复辟的理由")

    def test_contract_states_fail_closed_gate(self):
        text = _contract_section(_contract_text())
        assert "fail-closed" in text or "判失败" in text, (
            "契约须说明缺载荷处置会被产物硬门判失败（不产生假收口）")

    def test_disposition_template_carries_choice_payload_key(self):
        """处置记录模板含 choice_payload 可选键（且注明 revise_scenario_reverify
        必填），防载荷键随模板改写静默丢失。"""
        text = _contract_text()
        assert '"choice_payload"' in text, (
            "处置记录 JSON 模板丢失 choice_payload 键")
        # 模板键在 JSON 模板块内（"choice_payload": "..." 键值形态）
        assert '"choice_payload":' in text
        idx = text.index('"choice_payload":')
        tail = text[idx:idx + 400]
        assert "revise_scenario_reverify" in tail, (
            "模板键说明须指出 revise_scenario_reverify 时必填")
