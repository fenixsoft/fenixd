"""add-model-billing-cost-display 单元测试（tasks 1.3 / 2.3 / 3.3）。

覆盖：
- 配置层：llm.billing 校验拒绝矩阵、合法写入落盘、读侧回显（user/project/effective）
- 成本计算：usage 提取（_run_tail_insights）、compute_run_cost 匹配与四分项数值核对
- 接线：时间轴 run 节点 cost_usd、SPEC 详情 cost_summary（混合计价/全未计价/开关关）
"""

import copy
import json
from pathlib import Path

import pytest

from core.dashboard import data as dashboard_data

# ── 公共夹具构造 ──────────────────────────────────────────────

VALID_PROVIDERS = [
    {"name": "inferaiapi.com", "baseurl": "https://api.inferaiapi.com/v1", "apikey": "k1"},
]

VALID_PRICE = {
    "provider": "inferaiapi.com",
    "model": "deepseek-v4-flash",
    "input_per_million": 0.27,
    "output_per_million": 1.10,
    "cache_read_per_million": 0.07,
    "cache_creation_per_million": 0.28,
}


def valid_billing():
    return {"enabled": True, "prices": [copy.deepcopy(VALID_PRICE)]}


def valid_llm():
    return {"providers": copy.deepcopy(VALID_PROVIDERS), "billing": valid_billing()}


# ── 1.3 配置层：llm.billing 校验拒绝矩阵 / 合法写入 / 读侧回显 ──


class TestBillingWriteValidation:
    def _write(self, proot, llm):
        return dashboard_data.write_config(proot, {"llm": llm})

    def test_valid_billing_writes_and_persists(self, tmp_path):
        r = self._write(tmp_path, valid_llm())
        assert r["ok"] is True
        # 落盘校验：文件内容包含 billing 段（read_config 走同一文件）
        from core.config import ConfigLoader
        raw = ConfigLoader._load_optional_yaml(
            tmp_path / ".fenix" / "config.yaml", "test"
        )
        assert raw["llm"]["billing"]["enabled"] is True
        assert raw["llm"]["billing"]["prices"][0]["input_per_million"] == 0.27
        assert raw["llm"]["billing"]["prices"][0]["cache_creation_per_million"] == 0.28

    def test_negative_price_rejected(self, tmp_path):
        llm = valid_llm()
        llm["billing"]["prices"][0]["input_per_million"] = -0.1
        r = self._write(tmp_path, llm)
        assert r["ok"] is False
        assert "必须为非负数值" in r["error"]
        assert "prices[0]" in r["error"]

    def test_non_numeric_price_rejected(self, tmp_path):
        llm = valid_llm()
        llm["billing"]["prices"][0]["output_per_million"] = "abc"
        r = self._write(tmp_path, llm)
        assert r["ok"] is False
        assert "必须为非负数值" in r["error"]

    def test_missing_price_field_rejected(self, tmp_path):
        llm = valid_llm()
        del llm["billing"]["prices"][0]["cache_read_per_million"]
        r = self._write(tmp_path, llm)
        assert r["ok"] is False
        assert "cache_read_per_million" in r["error"]

    def test_duplicate_provider_model_rejected(self, tmp_path):
        llm = valid_llm()
        llm["billing"]["prices"].append(copy.deepcopy(VALID_PRICE))
        r = self._write(tmp_path, llm)
        assert r["ok"] is False
        assert "重复" in r["error"]
        assert "prices[1]" in r["error"]

    def test_unknown_provider_rejected(self, tmp_path):
        llm = valid_llm()
        llm["billing"]["prices"][0]["provider"] = "no-such-provider"
        r = self._write(tmp_path, llm)
        assert r["ok"] is False
        assert "引用了不存在的 provider" in r["error"]
        assert "no-such-provider" in r["error"]

    def test_non_bool_enabled_rejected(self, tmp_path):
        llm = valid_llm()
        llm["billing"]["enabled"] = "yes"
        r = self._write(tmp_path, llm)
        assert r["ok"] is False
        assert "enabled must be a boolean" in r["error"]

    def test_malformed_billing_shapes_rejected(self, tmp_path):
        llm = valid_llm()
        llm["billing"] = "on"
        r = self._write(tmp_path, llm)
        assert r["ok"] is False

        llm2 = valid_llm()
        llm2["billing"]["prices"] = {"provider": "x"}
        r2 = self._write(tmp_path, llm2)
        assert r2["ok"] is False
        assert "prices must be a list" in r2["error"]

        llm3 = valid_llm()
        llm3["billing"]["prices"] = ["oops"]
        r3 = self._write(tmp_path, llm3)
        assert r3["ok"] is False

    def test_billing_absent_is_not_validated(self, tmp_path):
        # 不带 billing 的 llm 段（既有行为）不受影响
        r = self._write(tmp_path, {"providers": copy.deepcopy(VALID_PROVIDERS)})
        assert r["ok"] is True

    def test_billing_zero_price_allowed(self, tmp_path):
        # 单价可为 0（免费），仍为合法非负数值
        llm = valid_llm()
        llm["billing"]["prices"][0]["input_per_million"] = 0
        r = self._write(tmp_path, llm)
        assert r["ok"] is True


class TestBillingReadPassthrough:
    def test_read_config_project_passthrough(self, tmp_path):
        cfg_dir = tmp_path / ".fenix"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "config.yaml").write_text(
            "llm:\n"
            "  providers:\n"
            "    - name: inferaiapi.com\n"
            "      baseurl: https://api.inferaiapi.com/v1\n"
            "      apikey: k1\n"
            "  billing:\n"
            "    enabled: true\n"
            "    prices:\n"
            "      - provider: inferaiapi.com\n"
            "        model: deepseek-v4-flash\n"
            "        input_per_million: 0.27\n"
            "        output_per_million: 1.10\n"
            "        cache_read_per_million: 0.07\n"
            "        cache_creation_per_million: 0.28\n",
            encoding="utf-8",
        )
        cfg = dashboard_data.read_config(tmp_path, scope="project")
        billing = cfg["llm"].get("billing")
        assert billing is not None
        assert billing["enabled"] is True
        assert billing["prices"][0]["provider"] == "inferaiapi.com"
        assert billing["prices"][0]["model"] == "deepseek-v4-flash"

    def test_read_config_user_passthrough(self, tmp_path, monkeypatch):
        user_cfg = tmp_path / "user" / "config.yaml"
        user_cfg.parent.mkdir(parents=True)
        user_cfg.write_text(
            "llm:\n"
            "  billing:\n"
            "    enabled: false\n"
            "    prices: []\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(dashboard_data, "USER_CONFIG_PATH", user_cfg)
        cfg = dashboard_data.read_config(tmp_path, scope="user")
        assert cfg["llm"]["billing"] == {"enabled": False, "prices": []}

    def test_read_effective_config_project_overrides_user(self, tmp_path, monkeypatch):
        # 用户级配置 bigmodel 价格；项目级 inferaiapi.com 价格 → effective 取项目级
        user_cfg = tmp_path / "user" / "config.yaml"
        user_cfg.parent.mkdir(parents=True)
        user_cfg.write_text(
            "llm:\n"
            "  providers:\n"
            "    - name: bigmodel\n"
            "      baseurl: https://x/v1\n"
            "      apikey: k2\n"
            "  billing:\n"
            "    enabled: true\n"
            "    prices:\n"
            "      - provider: bigmodel\n"
            "        model: glm-4\n"
            "        input_per_million: 1.0\n"
            "        output_per_million: 2.0\n"
            "        cache_read_per_million: 0.1\n"
            "        cache_creation_per_million: 0.2\n",
            encoding="utf-8",
        )
        import core.config as core_config
        monkeypatch.setattr(core_config, "USER_CONFIG_DIR", user_cfg.parent)

        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        (proot / ".fenix" / "config.yaml").write_text(
            "llm:\n"
            "  providers:\n"
            "    - name: inferaiapi.com\n"
            "      baseurl: https://api.inferaiapi.com/v1\n"
            "      apikey: k1\n"
            "  billing:\n"
            "    enabled: true\n"
            "    prices:\n"
            "      - provider: inferaiapi.com\n"
            "        model: deepseek-v4-flash\n"
            "        input_per_million: 0.27\n"
            "        output_per_million: 1.10\n"
            "        cache_read_per_million: 0.07\n"
            "        cache_creation_per_million: 0.28\n",
            encoding="utf-8",
        )
        eff = dashboard_data.read_effective_config(proot)
        assert eff["sources"]["llm"] == "project"
        prices = eff["llm"]["billing"]["prices"]
        assert prices[0]["provider"] == "inferaiapi.com"
        assert prices[0]["model"] == "deepseek-v4-flash"
        # 项目级覆盖用户级：不存在用户级 bigmodel 价格
        assert all(p["provider"] != "bigmodel" for p in prices)

    def test_billing_absent_default(self, tmp_path):
        # 无 billing 段 → read_config llm 无 billing 键（既有默认）
        cfg_dir = tmp_path / ".fenix"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "config.yaml").write_text(
            "llm:\n"
            "  providers:\n"
            "    - name: inferaiapi.com\n"
            "      baseurl: https://x\n"
            "      apikey: k1\n",
            encoding="utf-8",
        )
        cfg = dashboard_data.read_config(tmp_path, scope="project")
        assert "billing" not in (cfg["llm"] or {})


# ── 2.3 成本计算核心：usage 提取 + compute_run_cost ──


class TestRunTailInsightsUsage:
    def test_result_usage_extracted(self, tmp_path):
        """真实 jsonl 结构（task 7 夹具形态）：provider_marker + 多轮 assistant + result usage。"""
        run_file = tmp_path / "impl-spec-1788260701-a1.jsonl"
        run_file.write_text(
            "\n".join(
                json.dumps(e)
                for e in [
                    {"type": "provider_marker", "model": "deepseek-v4-flash",
                     "provider": "inferaiapi.com"},
                    {"type": "assistant", "content": "working"},
                    {"type": "result", "result": "done",
                     "usage": {
                         "input_tokens": 1_000_000,
                         "output_tokens": 100_000,
                         "cache_creation_input_tokens": 200_000,
                         "cache_read_input_tokens": 300_000,
                     }},
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        ins = dashboard_data._run_tail_insights(run_file)
        assert ins["summary"] == "done"
        assert ins["llm"] == "deepseek-v4-flash@inferaiapi.com"
        assert ins["usage"]["input_tokens"] == 1_000_000
        assert ins["usage"]["cache_read_input_tokens"] == 300_000

    def test_no_result_tail_usage_none(self, tmp_path):
        """无 result 事件（运行中/中断）→ usage None（不可计价）。"""
        run_file = tmp_path / "impl-spec-1788260702-a1.jsonl"
        run_file.write_text(
            json.dumps({"type": "provider_marker", "model": "m1", "provider": "p1"}) + "\n"
            + json.dumps({"type": "assistant", "content": "x"}) + "\n",
            encoding="utf-8",
        )
        ins = dashboard_data._run_tail_insights(run_file)
        assert ins["usage"] is None
        assert ins["llm"] == "m1@p1"

    def test_missing_file_usage_none(self, tmp_path):
        ins = dashboard_data._run_tail_insights(tmp_path / "nope.jsonl")
        assert ins["usage"] is None
        assert ins["summary"] == ""

    def test_split_llm_marker(self):
        model, provider = dashboard_data._split_llm_marker("deepseek-v4-flash@inferaiapi.com")
        assert model == "deepseek-v4-flash"
        assert provider == "inferaiapi.com"
        assert dashboard_data._split_llm_marker("") == ("", "")
        assert dashboard_data._split_llm_marker("foo@bar@baz") == ("foo@bar", "baz")


class TestComputeRunCost:
    USAGE = {
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
        "cache_read_input_tokens": 2_000_000,
        "cache_creation_input_tokens": 200_000,
    }

    def test_exact_match_four_part_sum(self):
        billing = {"enabled": True, "prices": [copy.deepcopy(VALID_PRICE)]}
        # 1×输入价 + 0.1×输出价 + 2×缓存读价 + 0.2×缓存写价
        cost = dashboard_data.compute_run_cost(
            self.USAGE, "deepseek-v4-flash", "inferaiapi.com", billing)
        expected = (1 * 0.27 + 0.1 * 1.10 + 2 * 0.07 + 0.2 * 0.28)
        assert cost is not None
        assert abs(cost - expected) < 1e-9

    def test_model_not_matched_returns_none(self):
        billing = {"enabled": True, "prices": [copy.deepcopy(VALID_PRICE)]}
        assert dashboard_data.compute_run_cost(
            self.USAGE, "other-model", "inferaiapi.com", billing) is None
        assert dashboard_data.compute_run_cost(
            self.USAGE, "deepseek-v4-flash", "other-provider", billing) is None

    def test_billing_disabled_returns_none(self):
        billing = {"enabled": False, "prices": [copy.deepcopy(VALID_PRICE)]}
        assert dashboard_data.compute_run_cost(
            self.USAGE, "deepseek-v4-flash", "inferaiapi.com", billing) is None

    def test_usage_missing_returns_none(self):
        billing = {"enabled": True, "prices": [copy.deepcopy(VALID_PRICE)]}
        assert dashboard_data.compute_run_cost(
            None, "deepseek-v4-flash", "inferaiapi.com", billing) is None
        assert dashboard_data.compute_run_cost(
            {}, "deepseek-v4-flash", "inferaiapi.com", billing) == 0.0

    def test_billing_missing_returns_none(self):
        assert dashboard_data.compute_run_cost(
            self.USAGE, "deepseek-v4-flash", "inferaiapi.com", None) is None

    def test_failover_marker_drives_match(self):
        """匹配键以 run 产物 marker 为准：failover 后实际网关的价格命中。"""
        billing = {"enabled": True, "prices": [
            copy.deepcopy(VALID_PRICE),
            {"provider": "bigmodel", "model": "deepseek-v4-flash",
             "input_per_million": 1.0, "output_per_million": 2.0,
             "cache_read_per_million": 0.1, "cache_creation_per_million": 0.2},
        ]}
        cost = dashboard_data.compute_run_cost(
            self.USAGE, "deepseek-v4-flash", "bigmodel", billing)
        expected = (1 * 1.0 + 0.1 * 2.0 + 2 * 0.1 + 0.2 * 0.2)
        assert cost is not None
        assert abs(cost - expected) < 1e-9

    def test_incomplete_price_row_returns_none(self):
        billing = {"enabled": True, "prices": [
            {"provider": "inferaiapi.com", "model": "deepseek-v4-flash",
             "input_per_million": 0.27, "output_per_million": 1.10,
             "cache_read_per_million": 0.07},  # 缺 cache_creation
        ]}
        assert dashboard_data.compute_run_cost(
            self.USAGE, "deepseek-v4-flash", "inferaiapi.com", billing) is None


# ── 3.3 接线：时间轴 run 节点 cost_usd + SPEC 详情 cost_summary ──

_USAGE10 = {
    "input_tokens": 1_000_000,
    "output_tokens": 100_000,
    "cache_read_input_tokens": 2_000_000,
    "cache_creation_input_tokens": 200_000,
}


def _billing_yaml():
    return (
        "llm:\n"
        "  providers:\n"
        "    - name: inferaiapi.com\n"
        "      baseurl: https://api.inferaiapi.com/v1\n"
        "      apikey: k1\n"
        "  billing:\n"
        "    enabled: true\n"
        "    prices:\n"
        "      - provider: inferaiapi.com\n"
        "        model: deepseek-v4-flash\n"
        "        input_per_million: 0.27\n"
        "        output_per_million: 1.10\n"
        "        cache_read_per_million: 0.07\n"
        "        cache_creation_per_million: 0.28\n"
    )


def _write_run(proot, name, model, usage=None):
    """写一个 run 产物；usage=None 时 result 事件不带 usage（中断/无 LLM）。"""
    events = [{"type": "provider_marker", "model": model, "provider": "inferaiapi.com"}]
    if usage is not None:
        events.append({"type": "result", "result": "done", "usage": usage})
    (proot / ".fenix" / "runs" / name).write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


def _make_project(tmp_path) -> Path:
    """构造带 STATE + billing 配置 + runs 目录的假项目。"""
    proot = tmp_path / "proj"
    (proot / ".fenix" / "runs").mkdir(parents=True)
    (proot / ".fenix" / "STATE.md").write_text(
        "### spec-demo\n\n- status: verified\n", encoding="utf-8")
    (proot / ".fenix" / "config.yaml").write_text(_billing_yaml(), encoding="utf-8")
    return proot


class TestTimelineRunCost:
    def test_priced_run_carries_cost_usd(self, tmp_path):
        proot = _make_project(tmp_path)
        _write_run(proot, "impl-spec-demo-1788260701-a1.jsonl", "deepseek-v4-flash", _USAGE10)
        timeline = dashboard_data.get_spec_timeline(proot, "spec-demo")
        runs = [e for e in timeline if e["kind"] == "run"]
        assert len(runs) == 1
        assert "cost_usd" in runs[0]
        assert abs(runs[0]["cost_usd"] - 0.576) < 1e-9  # 手工核对四分项

    def test_unpriced_and_interrupted_runs_have_no_cost(self, tmp_path):
        proot = _make_project(tmp_path)
        _write_run(proot, "impl-spec-demo-1788260701-a1.jsonl", "deepseek-v4-flash", _USAGE10)
        _write_run(proot, "impl-spec-demo-1788260702-a1.jsonl", "no-price-model", _USAGE10)
        _write_run(proot, "impl-spec-demo-1788260703-a1.jsonl", "deepseek-v4-flash", None)
        timeline = dashboard_data.get_spec_timeline(proot, "spec-demo")
        runs = [e for e in timeline if e["kind"] == "run"]
        assert len(runs) == 3
        assert "cost_usd" in runs[0]
        assert "cost_usd" not in runs[1]
        assert "cost_usd" not in runs[2]

    def test_billing_disabled_no_cost_anywhere(self, tmp_path):
        proot = _make_project(tmp_path)
        _write_run(proot, "impl-spec-demo-1788260701-a1.jsonl", "deepseek-v4-flash", _USAGE10)
        (proot / ".fenix" / "config.yaml").write_text(
            "llm:\n"
            "  providers:\n"
            "    - name: inferaiapi.com\n"
            "      baseurl: https://x\n"
            "      apikey: k1\n"
            "  billing:\n"
            "    enabled: false\n"
            "    prices: []\n",
            encoding="utf-8",
        )
        timeline = dashboard_data.get_spec_timeline(proot, "spec-demo")
        runs = [e for e in timeline if e["kind"] == "run"]
        assert runs
        assert all("cost_usd" not in e for e in runs)


class TestSpecDetailCostSummary:
    def _detail(self, proot, spec="spec-demo"):
        entries = dashboard_data.parse_state(proot)
        return dashboard_data.spec_detail(proot, spec, entries[spec])

    def test_mixed_priced_unpriced_annotation(self, tmp_path):
        proot = _make_project(tmp_path)
        _write_run(proot, "impl-spec-demo-1788260701-a1.jsonl", "deepseek-v4-flash", _USAGE10)
        _write_run(proot, "impl-spec-demo-1788260702-a1.jsonl", "no-price-model", _USAGE10)
        _write_run(proot, "impl-spec-demo-1788260703-a1.jsonl", "deepseek-v4-flash", _USAGE10)
        det = self._detail(proot)
        cs = det["cost_summary"]
        assert cs["priced_runs"] == 2
        assert cs["unpriced_runs"] == 1
        assert cs["computed_usd"] is not None
        assert abs(cs["computed_usd"] - 2 * 0.576) < 1e-9

    def test_all_unpriced_computed_none(self, tmp_path):
        proot = _make_project(tmp_path)
        _write_run(proot, "impl-spec-demo-1788260701-a1.jsonl", "no-price-model", _USAGE10)
        det = self._detail(proot)
        cs = det["cost_summary"]
        assert cs["priced_runs"] == 0
        assert cs["unpriced_runs"] == 1
        assert cs["computed_usd"] is None

    def test_no_runs_all_unpriced(self, tmp_path):
        proot = _make_project(tmp_path)
        det = self._detail(proot)
        assert det["cost_summary"] == {"computed_usd": None, "priced_runs": 0, "unpriced_runs": 0}

    def test_billing_disabled_cost_summary_absent(self, tmp_path):
        proot = _make_project(tmp_path)
        _write_run(proot, "impl-spec-demo-1788260701-a1.jsonl", "deepseek-v4-flash", _USAGE10)
        (proot / ".fenix" / "config.yaml").write_text(
            "llm:\n"
            "  providers:\n"
            "    - name: inferaiapi.com\n"
            "      baseurl: https://x\n"
            "      apikey: k1\n",
            encoding="utf-8",
        )
        det = self._detail(proot)
        assert det.get("cost_summary") is None
        assert all("cost_usd" not in e for e in det["timeline"] if e["kind"] == "run")
