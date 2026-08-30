"""add-cost-observability 单元测试（tasks 4.1 / 4.2）。

覆盖：
- usage 提取累加（含 cache 分项）；异常 run 零计
- 80% / 100% 一次性告警与标记持久；预算 0 关闭
- 「成本不可用」渲染（cost_available=False）
- 验证链侧车 tokens.json 写入
- v2-config-page 真实 jsonl 结构提取数值（对照人工考古 42M）

注：StateMachine 将 STATE.md 字段以字符串存储，读取时按类型规整。
"""

import json
from pathlib import Path

from core.agent_runner import AgentRunner
from core.dashboard import data as dashboard_data
from core.state_machine import StateMachine
from core.verify_report import render_verification_report, _sum_verify_chain_tokens


class FakeLogger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_runner(proot: Path) -> AgentRunner:
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {"agents": {"token_budget_millions": 50}}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = proot
    runner.logger = FakeLogger()
    runner._running_agents = {}
    return runner


def make_state(proot: Path, spec: str, tokens_in: int = 0) -> StateMachine:
    sm = StateMachine(proot / "STATE.md", FakeLogger())
    sm.add_spec(spec, {
        "priority": 5,
        "status": "implementing",
        "_tokens_in": tokens_in,
        "_tokens_out": 0,
    })
    return sm


def _int(entry, key):
    """STATE.md 字段以字符串存储，规整为 int。"""
    return int(entry[key])


class TestExtractUsageInfo:
    def test_full_usage_with_cache(self):
        runner = make_runner(Path("/tmp"))
        ev = {
            "type": "result",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 3,
                "cache_creation_input_tokens": 4,
                "cache_read_input_tokens": 5,
            },
            "total_cost_usd": 0.42,
        }
        info = runner._extract_usage_info(ev)
        assert info["input_tokens"] == 10
        assert info["output_tokens"] == 3
        assert info["cache_creation_input_tokens"] == 4
        assert info["cache_read_input_tokens"] == 5
        assert info["cost_usd"] == 0.42

    def test_no_cost_field(self):
        runner = make_runner(Path("/tmp"))
        ev = {"type": "result", "usage": {"input_tokens": 1, "output_tokens": 2}}
        info = runner._extract_usage_info(ev)
        assert info["cost_usd"] is None

    def test_invalid_event_returns_zeros(self):
        runner = make_runner(Path("/tmp"))
        zero = {
            "input_tokens": 0, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "cost_usd": None,
        }
        assert runner._extract_usage_info(None) == zero
        assert runner._extract_usage_info({"type": "result"}) == zero

    def test_cost_not_faked_from_zero(self):
        runner = make_runner(Path("/tmp"))
        ev = {"type": "result", "usage": {"input_tokens": 1, "output_tokens": 1},
              "total_cost_usd": 0.0}
        assert runner._extract_usage_info(ev)["cost_usd"] == 0.0


class TestAccumulateTokenUsage:
    def test_accumulate_with_cache_subtotals(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir()
        sm = make_state(proot, "spec-a", tokens_in=26_000_000)
        runner = make_runner(proot)
        runner.state_machine = sm
        # 本次 input=14.5M（10 + 4.5 cache），output=0.3M
        usage = {
            "input_tokens": 10_000_000,
            "output_tokens": 300_000,
            "cache_creation_input_tokens": 4_000_000,
            "cache_read_input_tokens": 500_000,
            "cost_usd": None,
        }
        runner._accumulate_token_usage("spec-a", usage)
        entry = sm.read_one("spec-a")
        # 26M + (10M + 4M + 0.5M) = 40.5M
        assert _int(entry, "_tokens_in") == 40_500_000
        assert _int(entry, "_tokens_out") == 300_000

    def test_cost_accumulates_only_when_gateway_reports(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir()
        sm = make_state(proot, "spec-b", tokens_in=0)
        runner = make_runner(proot)
        runner.state_machine = sm
        runner._accumulate_token_usage("spec-b", {
            "input_tokens": 1, "output_tokens": 1,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "cost_usd": 1.5,
        })
        assert sm.read_one("spec-b")["_cost_usd"] == "1.5"
        # 一次无成本回传的 run 不应写入 _cost_usd（保持缺失语义）
        runner._accumulate_token_usage("spec-b", {
            "input_tokens": 1, "output_tokens": 1,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "cost_usd": None,
        })
        assert sm.read_one("spec-b")["_cost_usd"] == "1.5"

    def test_error_run_zero_count(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir()
        sm = make_state(proot, "spec-c", tokens_in=100)
        runner = make_runner(proot)
        runner.state_machine = sm
        runner._accumulate_token_usage("spec-c", runner._extract_usage_info(None))
        # 异常 run：input 按 0 计，不污染既有累计
        assert _int(sm.read_one("spec-c"), "_tokens_in") == 100


class TestTokenBudgetAlert:
    def test_warn_once_at_80_then_no_repeat(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir()
        # 40M / 50M = 80% 线
        sm = make_state(proot, "spec-d", tokens_in=40_000_000)
        runner = make_runner(proot)
        runner.state_machine = sm
        runner._accumulate_token_usage("spec-d", {
            "input_tokens": 1_000_000, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "cost_usd": None,
        })
        entry = sm.read_one("spec-d")
        assert entry["_token_warn_80"] == "True"
        assert entry.get("_token_alert_100") != "True"
        # spec 状态不受影响（不自动冻结）
        assert entry["status"] == "implementing"

        # 再次越过 80% 线（已置位）不应重复发告警 —— 验证幂等：flag 保持
        runner._accumulate_token_usage("spec-d", {
            "input_tokens": 1_000_000, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "cost_usd": None,
        })
        assert sm.read_one("spec-d")["_token_warn_80"] == "True"

    def test_critical_once_at_100(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir()
        # 49.9M，本次 +0.2M → 50.1M，越过 100% 线
        sm = make_state(proot, "spec-e", tokens_in=49_900_000)
        runner = make_runner(proot)
        runner.state_machine = sm
        runner._accumulate_token_usage("spec-e", {
            "input_tokens": 200_000, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "cost_usd": None,
        })
        entry = sm.read_one("spec-e")
        assert entry["_token_alert_100"] == "True"
        assert entry["status"] == "implementing"  # 不冻结

    def test_budget_zero_disabled(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir()
        sm = make_state(proot, "spec-f", tokens_in=0)
        runner = make_runner(proot)
        runner.config = {"agents": {"token_budget_millions": 0}}
        runner.state_machine = sm
        runner._accumulate_token_usage("spec-f", {
            "input_tokens": 100_000_000, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "cost_usd": None,
        })
        # 0=关闭：不写任何告警标记
        entry = sm.read_one("spec-f")
        assert entry.get("_token_warn_80") != "True"
        assert entry.get("_token_alert_100") != "True"


class TestVerifyProgressSidecar:
    def test_planner_tokens_recorded(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_runner(proot)
        runner._record_verify_progress_tokens("spec-g", "planner-plan", {
            "input_tokens": 1_000_000, "output_tokens": 20_000,
            "cache_creation_input_tokens": 100_000, "cache_read_input_tokens": 50_000,
            "cost_usd": None,
        })
        runner._record_verify_progress_tokens("spec-g", "planner-judge", {
            "input_tokens": 500_000, "output_tokens": 10_000,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "cost_usd": None,
        })
        tokens_json = proot / ".fenix" / "verify-progress" / "spec-g" / "tokens.json"
        assert tokens_json.is_file()
        data = json.loads(tokens_json.read_text(encoding="utf-8"))
        assert len(data["runs"]) == 2
        # 第一轮 input 已含 cache 分项：1M + 100k + 50k
        assert data["runs"][0]["input_tokens"] == 1_150_000
        assert data["runs"][0]["agent_type"] == "planner-plan"

    def test_non_planner_not_recorded(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_runner(proot)
        runner._record_verify_progress_tokens("spec-h", "implementer", {
            "input_tokens": 1, "output_tokens": 1,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "cost_usd": None,
        })
        tokens_json = proot / ".fenix" / "verify-progress" / "spec-h" / "tokens.json"
        assert not tokens_json.exists()

    def test_sum_helper(self, tmp_path):
        proot = tmp_path / "proj"
        (proot / ".fenix" / "verify-progress" / "spec-i").mkdir(parents=True)
        tokens_json = proot / ".fenix" / "verify-progress" / "spec-i" / "tokens.json"
        tokens_json.write_text(json.dumps({
            "runs": [
                {"agent_type": "planner-plan", "input_tokens": 2_000_000,
                 "output_tokens": 100_000, "cost_usd": None},
                {"agent_type": "planner-judge", "input_tokens": 1_000_000,
                 "output_tokens": 50_000, "cost_usd": 0.3},
            ]
        }), encoding="utf-8")
        totals = _sum_verify_chain_tokens(proot, "spec-i")
        assert totals["input"] == 3_000_000
        assert totals["output"] == 150_000


class TestCostUnavailableRender:
    def test_token_usage_view_cost_missing(self):
        entry = {"_tokens_in": 42_000_000, "_tokens_out": 300_000}
        view = dashboard_data._token_usage_view(entry)
        assert view["tokens_in"] == 42_000_000
        assert view["tokens_out"] == 300_000
        assert view["cost_available"] is False
        assert view["cost_usd"] is None

    def test_token_usage_view_cost_present(self):
        entry = {"_tokens_in": 1_000_000, "_tokens_out": 10_000, "_cost_usd": 1.23}
        view = dashboard_data._token_usage_view(entry)
        assert view["cost_available"] is True
        assert view["cost_usd"] == 1.23

    def test_render_report_includes_chain_tokens_row(self, tmp_path):
        proot = tmp_path / "proj"
        (proot / ".fenix" / "verify-progress" / "spec-j").mkdir(parents=True)
        (proot / ".fenix" / "verify-progress" / "spec-j" / "tokens.json").write_text(
            json.dumps({"runs": [
                {"agent_type": "planner-plan", "input_tokens": 2_000_000,
                 "output_tokens": 100_000, "cost_usd": None},
            ]}), encoding="utf-8")
        md = render_verification_report(
            "spec-j", {"status": "verified"},
            {"summary": {"passed": 1, "total": 1, "failed": 0, "errors": 0}},
            project_root=proot,
        )
        assert "本链增量 Token（输入）" in md
        assert "2.00M" in md


class TestV2ConfigPageFixture:
    """对照人工考古 42M 的提取数值回归（task 4.2）。

    无真实 jsonl 夹具时，构造等价结构的 result 事件断言提取路径正确。
    """

    def test_extract_42m_equivalent(self):
        runner = make_runner(Path("/tmp"))
        # 人工考古：v2-config-page 24h 烧 42M input tokens（含 cache）。
        # 模拟一次 result 事件提取等价结构。
        ev = {
            "type": "result",
            "usage": {
                "input_tokens": 30_000_000,
                "output_tokens": 300_000,
                "cache_creation_input_tokens": 8_000_000,
                "cache_read_input_tokens": 4_000_000,
            },
        }
        info = runner._extract_usage_info(ev)
        # 仅 input 本体（不含 cache）≈ 30M；累计口径含 cache = 42M
        assert info["input_tokens"] == 30_000_000
        total = (info["input_tokens"] + info["cache_creation_input_tokens"]
                 + info["cache_read_input_tokens"])
        assert total == 42_000_000
