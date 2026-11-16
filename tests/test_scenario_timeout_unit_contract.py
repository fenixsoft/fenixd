"""scenario-timeout-unit-contract 单元测试。

覆盖 SPEC evo-scenario-timeout-unit-contract 全部场景（tasks.md 3.1 六场景）：
1. 毫秒形态 timeout 值报错含「疑似毫秒」换算嫌疑提示
2. 毫秒形态 duration 值报错含同款提示
3. 秒级超限（2400，不可被 1000 整除）不误报嫌疑
4. 合法秒值通过校验
5. 提示词文本含 timeout/duration 单位约定且上限数值与 MAX_STEP_TIMEOUT 一致
   （防漂移装置：静态文本里的「1800」import 常量做文本断言）
6. 含非法时长的场景集 validate_scenario_dicts errors 非空
   （「单位错误不落盘」整批退回现状回归）
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.verify_engine.scenarios import (
    MAX_STEP_TIMEOUT,
    validate_scenario_dicts,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = REPO_ROOT / "agents" / "planner-plan.md"


# ── 夹具 ─────────────────────────────────────────────────────────

def _cli_scenario(sid="cli-timeout-probe", timeout=None):
    """最小合法 cli 场景（run + exit_code 断言），可注入步骤 timeout。"""
    step = {"action": "run", "command": "echo ok"}
    if timeout is not None:
        step["timeout"] = timeout
    return {
        "id": sid,
        "description": "cli timeout 单位契约探针",
        "kind": "cli",
        "steps": [step],
        "assertions": [{"type": "exit_code", "expected": 0}],
    }


def _api_sse_scenario(sid="api-sse-duration-probe", duration=None):
    """最小合法 api 场景（sse_connect + sse_event_count 断言），可注入 duration。"""
    step = {"action": "sse_connect", "url": "https://127.0.0.1:19000/events"}
    if duration is not None:
        step["duration"] = duration
    return {
        "id": sid,
        "description": "api sse duration 单位契约探针",
        "kind": "api",
        "steps": [step],
        "assertions": [{"type": "sse_event_count", "min": 1}],
    }


# ── 1/2. 毫秒形态值触发嫌疑提示 ──────────────────────────────────

class TestMsFormHint:
    """毫秒形态超限值触发换算嫌疑提示（spec「非法 timeout 报错带换算嫌疑提示」）。"""

    def test_ms_form_timeout_error_carries_hint(self):
        """timeout=180000.0（毫秒形态）报错含嫌疑提示、继续回显数值与上限。"""
        errors = validate_scenario_dicts([_cli_scenario(timeout=180000.0)])
        assert errors, "毫秒形态 timeout 须被量级校验拒绝"
        joined = "\n".join(errors)
        assert "超过上限" in joined
        assert "180000.0" in joined, "报错必须继续回显原始数值"
        assert "疑似毫秒" in joined
        assert "建议除以 1000" in joined

    def test_ms_form_duration_error_carries_same_hint(self):
        """duration=60000.0（毫秒形态）报错含同款提示（duration 同构暴露面）。"""
        errors = validate_scenario_dicts([_api_sse_scenario(duration=60000.0)])
        assert errors, "毫秒形态 duration 须被量级校验拒绝"
        joined = "\n".join(errors)
        assert "超过上限" in joined
        assert "60000.0" in joined
        assert "疑似毫秒" in joined
        assert "建议除以 1000" in joined


# ── 3. 秒级超限不误报嫌疑 ────────────────────────────────────────

class TestSecondFormNoFalseHint:
    def test_second_form_overlimit_no_false_hint(self):
        """timeout=2400（秒级超限、不可被 1000 整除）只报超限事实，不附嫌疑提示。"""
        errors = validate_scenario_dicts([_cli_scenario(timeout=2400)])
        assert errors, "2400 秒超上限须被拒绝"
        joined = "\n".join(errors)
        assert "超过上限" in joined
        assert "2400" in joined
        assert "疑似毫秒" not in joined


# ── 4. 合法秒值通过校验 ──────────────────────────────────────────

class TestLegalSecondValues:
    def test_legal_second_values_pass(self):
        """timeout=1500 / duration=900 均为合法秒值，零报错通过验收。"""
        assert validate_scenario_dicts([_cli_scenario(timeout=1500)]) == []
        assert validate_scenario_dicts([_api_sse_scenario(duration=900)]) == []


# ── 5. 提示词单位约定与常量一致（防漂移装置） ────────────────────

class TestPromptUnitContract:
    """planner-plan.md 单位约定在场 + 上限数值与 MAX_STEP_TIMEOUT 防漂移一致
    （design.md Design 3：静态文本里的「1800」须有防漂移装置）。"""

    def _rule_line(self) -> str:
        text = PROMPT_PATH.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if "时长字段单位为秒" in ln]
        assert lines, "planner-plan.md 缺少「时长字段单位为秒」约定行"
        return lines[0]

    def test_prompt_names_both_fields_with_unit(self):
        """约定行同时点名 timeout/duration、声明秒单位与整批退回后果。"""
        line = self._rule_line()
        assert "timeout" in line
        assert "duration" in line
        assert "秒" in line
        assert "MAX_STEP_TIMEOUT" in line, "约定须锚定校验层常量名"
        # 可选字段行（:124）同款注解在场，规划器在字段清单处即见单位
        opt_lines = [ln for ln in PROMPT_PATH.read_text(encoding="utf-8").splitlines()
                     if "时长类可选字段" in ln]
        assert opt_lines, "可选字段清单行缺单位注解"

    def test_prompt_upper_limit_matches_constant(self):
        """约定行声明的上限数值与 scenarios.MAX_STEP_TIMEOUT 常量一致。"""
        line = self._rule_line()
        m = re.search(r"上限\s*([0-9]+(?:\.[0-9]+)?)\s*秒", line)
        assert m, "约定行未声明上限数值"
        assert float(m.group(1)) == MAX_STEP_TIMEOUT


# ── 6. 单位错误不落盘（整批退回现状回归） ────────────────────────

class TestUnitErrorNotPersisted:
    """含非法 timeout 的场景集整批退回（写前预校验语义不变）。"""

    def test_mixed_set_rejected_whole_batch(self):
        """合法+非法混集 errors 非空、报错定位到非法条目（整批拒绝）。"""
        raw = [
            _cli_scenario(sid="cli-ok", timeout=600),
            _cli_scenario(sid="cli-bad", timeout=1800000.0),
        ]
        errors = validate_scenario_dicts(raw)
        assert errors, "含非法 timeout 的场景集须整批退回（errors 非空）"
        joined = "\n".join(errors)
        assert "cli-bad" in joined, "报错须定位到非法条目"

    def test_valid_set_still_passes(self):
        """对照：全合法混合 kind 场景集照常通过（闸门只拒非法集，语义无扩大）。"""
        assert validate_scenario_dicts([
            _cli_scenario(sid="cli-ok", timeout=600),
            _api_sse_scenario(sid="api-ok", duration=900),
        ]) == []
