"""improve-provider-billing-config 单元测试（task 4.1 按新结构与新匹配语义重写）。

覆盖：
- 配置层：providers[i].billing 校验拒绝矩阵、合法写入落盘（内嵌结构、无顶层 llm.billing）、
  读侧回显（user/project/effective）、顶层旧形态被剥离
- 成本计算：usage 提取（_run_tail_insights）、compute_run_cost 卡片开关 + 行 model 匹配
  与四分项数值核对、failover 按实际网关归属
- 计价表收集：_load_billing_config 从 providers 收集、关闭卡片不入表、容错空表
- 接线：时间轴 run 节点 cost_usd、SPEC 详情 cost_summary（混合计价/全未计价/计费关）
"""

import copy
import json
from pathlib import Path

import pytest

from core.dashboard import data as dashboard_data

# ── 公共夹具构造（新结构：billing 内嵌 provider，价格行无 provider 字段） ──


def valid_price(model="deepseek-v4-flash") -> dict:
    return {
        "model": model,
        "input_per_million": 0.27,
        "output_per_million": 1.10,
        "cache_read_per_million": 0.07,
        "cache_creation_per_million": 0.28,
    }


def valid_provider(model="deepseek-v4-flash", enabled=True,
                   prices=None, name="inferaiapi.com") -> dict:
    return {
        "name": name,
        "baseurl": "https://api.inferaiapi.com/v1",
        "apikey": "k1",
        "model": model,
        "billing": {
            "enabled": enabled,
            "prices": prices if prices is not None else [valid_price(model)],
        },
    }


def valid_llm():
    return {"providers": [valid_provider()]}


# ── 配置层：providers[i].billing 校验拒绝矩阵 / 合法写入 / 读侧回显 ──


class TestBillingWriteValidation:
    def _write(self, proot, llm):
        r = dashboard_data.write_config(proot, {"llm": llm})
        return r

    def test_valid_provider_billing_writes_and_persists(self, tmp_path):
        r = self._write(tmp_path, valid_llm())
        assert r["ok"] is True
        # 落盘校验：billing 内嵌于 providers[0]，文件无顶层 llm.billing
        from core.config import ConfigLoader
        raw = ConfigLoader._load_optional_yaml(
            tmp_path / ".fenix" / "config.yaml", "test"
        )
        assert "billing" not in raw["llm"]
        prov = raw["llm"]["providers"][0]
        assert prov["billing"]["enabled"] is True
        assert prov["billing"]["prices"][0]["input_per_million"] == 0.27
        assert prov["billing"]["prices"][0]["model"] == "deepseek-v4-flash"
        assert "provider" not in prov["billing"]["prices"][0]

    def test_negative_price_rejected(self, tmp_path):
        llm = valid_llm()
        llm["providers"][0]["billing"]["prices"][0]["input_per_million"] = -0.1
        r = self._write(tmp_path, llm)
        assert r["ok"] is False
        assert "必须为非负数值" in r["error"]
        assert "prices[0]" in r["error"]
        assert "providers[0]" in r["error"]

    def test_non_numeric_price_rejected(self, tmp_path):
        llm = valid_llm()
        llm["providers"][0]["billing"]["prices"][0]["output_per_million"] = "abc"
        r = self._write(tmp_path, llm)
        assert r["ok"] is False
        assert "必须为非负数值" in r["error"]

    def test_missing_price_field_rejected(self, tmp_path):
        llm = valid_llm()
        del llm["providers"][0]["billing"]["prices"][0]["cache_read_per_million"]
        r = self._write(tmp_path, llm)
        assert r["ok"] is False
        assert "cache_read_per_million" in r["error"]

    def test_duplicate_model_in_card_rejected(self, tmp_path):
        llm = valid_llm()
        llm["providers"][0]["billing"]["prices"].append(valid_price())
        r = self._write(tmp_path, llm)
        assert r["ok"] is False
        assert "重复" in r["error"]
        assert "prices[1]" in r["error"]

    def test_duplicate_model_across_cards_allowed(self, tmp_path):
        # 同一卡片内 model 唯一；不同卡片可同 model（挂靠各自卡片价格）
        llm = {"providers": [
            valid_provider(name="inferaiapi.com"),
            valid_provider(name="bigmodel"),
        ]}
        r = self._write(tmp_path, llm)
        assert r["ok"] is True

    def test_non_bool_enabled_rejected(self, tmp_path):
        llm = valid_llm()
        llm["providers"][0]["billing"]["enabled"] = "yes"
        r = self._write(tmp_path, llm)
        assert r["ok"] is False
        assert "enabled must be a boolean" in r["error"]

    def test_malformed_billing_shapes_rejected(self, tmp_path):
        llm = valid_llm()
        llm["providers"][0]["billing"] = "on"
        r = self._write(tmp_path, llm)
        assert r["ok"] is False
        assert "must be an object" in r["error"]

        llm2 = valid_llm()
        llm2["providers"][0]["billing"]["prices"] = {"model": "x"}
        r2 = self._write(tmp_path, llm2)
        assert r2["ok"] is False
        assert "prices must be a list" in r2["error"]

        llm3 = valid_llm()
        llm3["providers"][0]["billing"]["prices"] = ["oops"]
        r3 = self._write(tmp_path, llm3)
        assert r3["ok"] is False

    def test_billing_absent_is_not_validated(self, tmp_path):
        # 不带 billing 的 llm 段（既有行为）不受影响
        r = self._write(tmp_path, {"providers": [{
            "name": "inferaiapi.com", "baseurl": "https://x",
            "apikey": "k1",
        }]})
        assert r["ok"] is True

    def test_billing_zero_price_allowed(self, tmp_path):
        # 单价可为 0（免费），仍为合法非负数值
        llm = valid_llm()
        llm["providers"][0]["billing"]["prices"][0]["input_per_million"] = 0
        r = self._write(tmp_path, llm)
        assert r["ok"] is True

    def test_top_level_llm_billing_stripped_on_save(self, tmp_path):
        # 旧客户端仍提交顶层 llm.billing → 落盘剥离（D1：文件永无顶层 llm.billing）
        llm = valid_llm()
        llm["billing"] = {"enabled": True, "prices": []}
        r = self._write(tmp_path, llm)
        assert r["ok"] is True
        from core.config import ConfigLoader
        raw = ConfigLoader._load_optional_yaml(
            tmp_path / ".fenix" / "config.yaml", "test"
        )
        assert "billing" not in raw["llm"]
        assert raw["llm"]["providers"][0]["billing"]["enabled"] is True

    def test_off_card_prices_persist_under_billing_false(self, tmp_path):
        # 关闭卡片仍可携带 billing.enabled=false + prices=[]（前端组装形态）
        llm = {"providers": [{
            "name": "inferaiapi.com", "baseurl": "https://x", "apikey": "k1",
            "billing": {"enabled": False, "prices": []},
        }]}
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
            "      billing:\n"
            "        enabled: true\n"
            "        prices:\n"
            "          - model: deepseek-v4-flash\n"
            "            input_per_million: 0.27\n"
            "            output_per_million: 1.10\n"
            "            cache_read_per_million: 0.07\n"
            "            cache_creation_per_million: 0.28\n",
            encoding="utf-8",
        )
        cfg = dashboard_data.read_config(tmp_path, scope="project")
        prov = cfg["llm"]["providers"][0]
        assert prov["billing"]["enabled"] is True
        assert prov["billing"]["prices"][0]["model"] == "deepseek-v4-flash"
        assert "provider" not in prov["billing"]["prices"][0]

    def test_read_config_user_passthrough(self, tmp_path, monkeypatch):
        user_cfg = tmp_path / "user" / "config.yaml"
        user_cfg.parent.mkdir(parents=True)
        user_cfg.write_text(
            "llm:\n"
            "  providers:\n"
            "    - name: bigmodel\n"
            "      baseurl: https://x/v1\n"
            "      apikey: k2\n"
            "      billing:\n"
            "        enabled: false\n"
            "        prices: []\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(dashboard_data, "USER_CONFIG_PATH", user_cfg)
        cfg = dashboard_data.read_config(tmp_path, scope="user")
        assert cfg["llm"]["providers"][0]["billing"] == {"enabled": False, "prices": []}

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
            "      billing:\n"
            "        enabled: true\n"
            "        prices:\n"
            "          - model: glm-4\n"
            "            input_per_million: 1.0\n"
            "            output_per_million: 2.0\n"
            "            cache_read_per_million: 0.1\n"
            "            cache_creation_per_million: 0.2\n",
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
            "      billing:\n"
            "        enabled: true\n"
            "        prices:\n"
            "          - model: deepseek-v4-flash\n"
            "            input_per_million: 0.27\n"
            "            output_per_million: 1.10\n"
            "            cache_read_per_million: 0.07\n"
            "            cache_creation_per_million: 0.28\n",
            encoding="utf-8",
        )
        eff = dashboard_data.read_effective_config(proot)
        assert eff["sources"]["llm"] == "project"
        provs = eff["llm"]["providers"]
        assert provs[0]["name"] == "inferaiapi.com"
        assert provs[0]["billing"]["prices"][0]["model"] == "deepseek-v4-flash"
        # 项目级覆盖用户级：不存在用户级 bigmodel
        assert all(p["name"] != "bigmodel" for p in provs)

    def test_billing_absent_default(self, tmp_path):
        # 无 billing 段 → provider 内无 billing 键
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
        assert "billing" not in cfg["llm"]["providers"][0]


# ── 计价表收集：_load_billing_config ──


class TestLoadBillingTable:
    def _config_root(self, tmp_path, yaml_text):
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        (proot / ".fenix" / "config.yaml").write_text(yaml_text, encoding="utf-8")
        return proot

    def test_collects_enabled_cards_only(self, tmp_path):
        proot = self._config_root(
            tmp_path,
            "llm:\n"
            "  providers:\n"
            "    - name: prov-on\n"
            "      baseurl: https://x\n"
            "      apikey: k\n"
            "      billing:\n"
            "        enabled: true\n"
            "        prices:\n"
            "          - model: m1\n"
            "            input_per_million: 1\n"
            "            output_per_million: 2\n"
            "            cache_read_per_million: 0.1\n"
            "            cache_creation_per_million: 0.2\n"
            "    - name: prov-off\n"
            "      baseurl: https://x\n"
            "      apikey: k\n"
            "      billing:\n"
            "        enabled: false\n"
            "        prices: []\n"
            "    - name: prov-plain\n"
            "      baseurl: https://x\n"
            "      apikey: k\n",
        )
        table = dashboard_data._load_billing_config(proot)
        assert "prov-on" in table and table["prov-on"]["enabled"] is True
        assert "prov-off" not in table
        assert "prov-plain" not in table

    def test_missing_config_returns_empty_table(self, tmp_path, monkeypatch):
        # 用户级配置隔离（isolated_user_config 惯例）：_load_billing_config 经
        # read_effective_config 合并用户级 ~/.fenix/config.yaml，本机该文件可能
        # 显式声明 billing 卡片，断言「缺省空表」不隔离就会环境敏感假失败。
        user_dir = tmp_path / "user-fenix"
        monkeypatch.setattr("core.config.USER_CONFIG_DIR", user_dir)
        monkeypatch.setattr(dashboard_data, "USER_CONFIG_PATH", user_dir / "config.yaml")
        proot = tmp_path / "noproj"
        (proot / ".fenix").mkdir(parents=True)
        assert dashboard_data._load_billing_config(proot) == {}

    def test_malformed_provider_billing_skipped(self, tmp_path):
        # enabled 非布尔异常形态（字符串 "yes"）→ 跳过该卡片不计价，不崩溃（容错）
        proot = self._config_root(
            tmp_path,
            "llm:\n"
            "  providers:\n"
            "    - name: prov-weird\n"
            "      baseurl: https://x\n"
            "      apikey: k\n"
            "      billing:\n"
            "        enabled: \"yes\"\n"
            "        prices: []\n",
        )
        table = dashboard_data._load_billing_config(proot)
        assert table == {}


# ── 成本计算核心：usage 提取 + compute_run_cost ──


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

    def _table(self, enabled=True, model="deepseek-v4-flash",
               provider="inferaiapi.com", prices=None):
        return {
            provider: {
                "enabled": enabled,
                "prices": prices if prices is not None else [valid_price(model)],
            }
        }

    def test_exact_match_four_part_sum(self):
        table = self._table()
        # 1×输入价 + 0.1×输出价 + 2×缓存读价 + 0.2×缓存写价
        cost = dashboard_data.compute_run_cost(
            self.USAGE, "deepseek-v4-flash", "inferaiapi.com", table)
        expected = (1 * 0.27 + 0.1 * 1.10 + 2 * 0.07 + 0.2 * 0.28)
        assert cost is not None
        assert abs(cost - expected) < 1e-9

    def test_model_not_matched_returns_none(self):
        table = self._table()
        assert dashboard_data.compute_run_cost(
            self.USAGE, "other-model", "inferaiapi.com", table) is None

    def test_provider_not_in_table_returns_none(self):
        table = self._table()
        assert dashboard_data.compute_run_cost(
            self.USAGE, "deepseek-v4-flash", "no-such-provider", table) is None

    def test_card_disabled_returns_none(self):
        table = self._table(enabled=False)
        assert dashboard_data.compute_run_cost(
            self.USAGE, "deepseek-v4-flash", "inferaiapi.com", table) is None

    def test_usage_missing_returns_none(self):
        table = self._table()
        assert dashboard_data.compute_run_cost(
            None, "deepseek-v4-flash", "inferaiapi.com", table) is None
        assert dashboard_data.compute_run_cost(
            {}, "deepseek-v4-flash", "inferaiapi.com", table) == 0.0

    def test_billing_table_missing_returns_none(self):
        assert dashboard_data.compute_run_cost(
            self.USAGE, "deepseek-v4-flash", "inferaiapi.com", None) is None
        assert dashboard_data.compute_run_cost(
            self.USAGE, "deepseek-v4-flash", "inferaiapi.com", {}) is None

    def test_failover_attributed_to_actual_gateway(self):
        """匹配键以 run 产物 marker 为准：failover 后按实际完成网关卡片计价。"""
        table = self._table(provider="bigmodel", prices=[{
            "model": "deepseek-v4-flash",
            "input_per_million": 1.0, "output_per_million": 2.0,
            "cache_read_per_million": 0.1, "cache_creation_per_million": 0.2,
        }])
        cost = dashboard_data.compute_run_cost(
            self.USAGE, "deepseek-v4-flash", "bigmodel", table)
        expected = (1 * 1.0 + 0.1 * 2.0 + 2 * 0.1 + 0.2 * 0.2)
        assert cost is not None
        assert abs(cost - expected) < 1e-9
        # 起始 provider 未开启/无表项：按实际网关归属，与其配置无关
        assert dashboard_data.compute_run_cost(
            self.USAGE, "deepseek-v4-flash", "inferaiapi.com", table) is None

    def test_incomplete_price_row_returns_none(self):
        table = self._table(prices=[{
            "model": "deepseek-v4-flash",
            "input_per_million": 0.27, "output_per_million": 1.10,
            "cache_read_per_million": 0.07,  # 缺 cache_creation
        }])
        assert dashboard_data.compute_run_cost(
            self.USAGE, "deepseek-v4-flash", "inferaiapi.com", table) is None


# ── 接线：时间轴 run 节点 cost_usd + SPEC 详情 cost_summary ──

_USAGE10 = {
    "input_tokens": 1_000_000,
    "output_tokens": 100_000,
    "cache_read_input_tokens": 2_000_000,
    "cache_creation_input_tokens": 200_000,
}


def _billing_yaml(extra=""):
    """内嵌 billing 项目配置（inferaiapi.com 卡片开启 + deepseek-v4-flash 价格）。"""
    return (
        "llm:\n"
        "  providers:\n"
        "    - name: inferaiapi.com\n"
        "      baseurl: https://api.inferaiapi.com/v1\n"
        "      apikey: k1\n"
        "      billing:\n"
        "        enabled: true\n"
        "        prices:\n"
        "          - model: deepseek-v4-flash\n"
        "            input_per_million: 0.27\n"
        "            output_per_million: 1.10\n"
        "            cache_read_per_million: 0.07\n"
        "            cache_creation_per_million: 0.28\n"
        + extra
    )


def _off_billing_yaml():
    """卡片开关关闭的内嵌 billing 项目配置（enabled=false + 空价格）。"""
    return (
        "llm:\n"
        "  providers:\n"
        "    - name: inferaiapi.com\n"
        "      baseurl: https://x\n"
        "      apikey: k1\n"
        "      billing:\n"
        "        enabled: false\n"
        "        prices: []\n"
    )


def _write_run(proot, name, model, usage=None, provider="inferaiapi.com"):
    """写一个 run 产物；usage=None 时 result 事件不带 usage（中断/无 LLM）。"""
    events = [{"type": "provider_marker", "model": model, "provider": provider}]
    if usage is not None:
        events.append({"type": "result", "result": "done", "usage": usage})
    (proot / ".fenix" / "runs" / name).write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


def _make_project(tmp_path) -> Path:
    """构造带 STATE + 内嵌 billing 配置 + runs 目录的假项目。"""
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

    def test_unpriced_model_and_interrupted_runs_have_no_cost(self, tmp_path):
        proot = _make_project(tmp_path)
        _write_run(proot, "impl-spec-demo-1788260701-a1.jsonl", "deepseek-v4-flash", _USAGE10)
        _write_run(proot, "impl-spec-demo-1788260702-a1.jsonl", "no-price-model", _USAGE10)
        _write_run(proot, "impl-spec-demo-1788260703-a1.jsonl", "deepseek-v4-flash", None)
        timeline = dashboard_data.get_spec_timeline(proot, "spec-demo")
        runs = [e for e in timeline if e["kind"] == "run"]
        assert len(runs) == 3
        assert "cost_usd" in runs[0]
        assert "cost_usd" not in runs[1]   # 模型不匹配 → unpriced
        assert "cost_usd" not in runs[2]   # usage 缺失 → unpriced

    def test_off_card_runs_have_no_cost(self, tmp_path):
        # 卡片开关关闭的 provider：即使模型匹配也计入时间轴无 cost 字段
        proot = _make_project(tmp_path)
        (proot / ".fenix" / "config.yaml").write_text(_off_billing_yaml(), encoding="utf-8")
        _write_run(proot, "impl-spec-demo-1788260701-a1.jsonl", "deepseek-v4-flash", _USAGE10)
        timeline = dashboard_data.get_spec_timeline(proot, "spec-demo")
        runs = [e for e in timeline if e["kind"] == "run"]
        assert runs
        assert all("cost_usd" not in e for e in runs)

    def test_no_billing_config_no_cost_anywhere(self, tmp_path):
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
        timeline = dashboard_data.get_spec_timeline(proot, "spec-demo")
        runs = [e for e in timeline if e["kind"] == "run"]
        assert runs
        assert all("cost_usd" not in e for e in runs)

    def test_failover_run_priced_by_actual_gateway(self, tmp_path):
        # 卡片 A 开启计价；run 经 failover 由 A 切到 B 完成 → 按 B 卡片价格（匹配 B）
        proot = tmp_path / "proj"
        (proot / ".fenix" / "runs").mkdir(parents=True)
        (proot / ".fenix" / "STATE.md").write_text(
            "### spec-demo\n\n- status: verified\n", encoding="utf-8")
        (proot / ".fenix" / "config.yaml").write_text(
            "llm:\n"
            "  providers:\n"
            "    - name: inferaiapi.com\n"
            "      baseurl: https://x\n"
            "      apikey: k\n"
            "      billing:\n"
            "        enabled: false\n"
            "        prices: []\n"
            "    - name: bigmodel\n"
            "      baseurl: https://x\n"
            "      apikey: k\n"
            "      billing:\n"
            "        enabled: true\n"
            "        prices:\n"
            "          - model: deepseek-v4-flash\n"
            "            input_per_million: 1.0\n"
            "            output_per_million: 2.0\n"
            "            cache_read_per_million: 0.1\n"
            "            cache_creation_per_million: 0.2\n",
            encoding="utf-8",
        )
        _write_run(proot, "impl-spec-demo-1788260701-a1.jsonl", "deepseek-v4-flash",
                   _USAGE10, provider="bigmodel")
        timeline = dashboard_data.get_spec_timeline(proot, "spec-demo")
        runs = [e for e in timeline if e["kind"] == "run"]
        assert len(runs) == 1
        assert abs(runs[0]["cost_usd"] - (1 * 1.0 + 0.1 * 2.0 + 2 * 0.1 + 0.2 * 0.2)) < 1e-9


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

    def test_off_card_runs_all_unpriced(self, tmp_path):
        # 卡片开关关闭 → 无开启卡片（计价表空）→ cost_summary 不下发（前端不渲染）
        proot = _make_project(tmp_path)
        (proot / ".fenix" / "config.yaml").write_text(_off_billing_yaml(), encoding="utf-8")
        _write_run(proot, "impl-spec-demo-1788260701-a1.jsonl", "deepseek-v4-flash", _USAGE10)
        det = self._detail(proot)
        assert det.get("cost_summary") is None
        assert all("cost_usd" not in e for e in det["timeline"] if e["kind"] == "run")

    def test_no_runs_all_unpriced(self, tmp_path):
        proot = _make_project(tmp_path)
        det = self._detail(proot)
        assert det["cost_summary"] == {"computed_usd": None, "priced_runs": 0, "unpriced_runs": 0}

    def test_no_billing_config_cost_summary_absent(self, tmp_path):
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