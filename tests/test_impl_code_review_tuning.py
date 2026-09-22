"""add-impl-code-review-tuning 测试。

覆盖 tasks 7.1-7.3b：
- 7.1 三读取器（timeout_sec/concurrency/effort）：缺省回退 / 非法值回退 /
      合法透传 / 项目级覆盖 / 三读取器互不牵连
- 7.2 runner._write_run_ocr_config 注入 timeout_sec（落盘 JSON 断言，
      含显式值与缺省值两例）
- 7.3 _impl_code_review_section 命令串含 --concurrency / --effort
      （显式值与缺省值两例）、不含 --max-tokens-budget、开关关闭零注入
- 7.3b 改写后成本控制文案与新命令示例不冲突（段内不得再出现
      「自行选择 effort」类措辞）

对齐 spec「配置读取器」四个 Scenario（键缺失取缺省 / 非法值回退缺省 /
合法值透传 / 项目级覆盖用户级）。
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import ConfigLoader


# ── 7.1 三读取器 ──────────────────────────────────────────────────────


class TestGetImplCodeReviewTimeoutSec:
    """ConfigLoader.get_impl_code_review_timeout_sec：缺省 600，仅正整数 int。"""

    def test_missing_verify_section(self):
        """verify 节缺失 → 600"""
        assert ConfigLoader.get_impl_code_review_timeout_sec({}) == 600

    def test_verify_not_dict(self):
        """verify 节非 dict → 600"""
        assert ConfigLoader.get_impl_code_review_timeout_sec({"verify": "bad"}) == 600

    def test_missing_key(self):
        """verify 存在但无该键 → 600（spec：键缺失取缺省）"""
        assert ConfigLoader.get_impl_code_review_timeout_sec({"verify": {}}) == 600

    def test_none_value(self):
        """值为 None → 600"""
        assert ConfigLoader.get_impl_code_review_timeout_sec(
            {"verify": {"impl_code_review_timeout_sec": None}}
        ) == 600

    def test_string_value(self):
        """值为 "abc"（非数字字符串）→ 600（spec：非法值回退缺省）"""
        assert ConfigLoader.get_impl_code_review_timeout_sec(
            {"verify": {"impl_code_review_timeout_sec": "abc"}}
        ) == 600

    def test_zero_and_negative(self):
        """值为 0 / -5（≤0）→ 600"""
        assert ConfigLoader.get_impl_code_review_timeout_sec(
            {"verify": {"impl_code_review_timeout_sec": 0}}
        ) == 600
        assert ConfigLoader.get_impl_code_review_timeout_sec(
            {"verify": {"impl_code_review_timeout_sec": -5}}
        ) == 600

    def test_float_value(self):
        """值为 900.5（float）→ 600（仅接受 int）"""
        assert ConfigLoader.get_impl_code_review_timeout_sec(
            {"verify": {"impl_code_review_timeout_sec": 900.5}}
        ) == 600

    def test_bool_value(self):
        """值为 True（bool 不算 int）→ 600"""
        assert ConfigLoader.get_impl_code_review_timeout_sec(
            {"verify": {"impl_code_review_timeout_sec": True}}
        ) == 600

    def test_valid_positive_int(self):
        """值为 900（合法正整数）→ 900（spec：合法值透传）"""
        assert ConfigLoader.get_impl_code_review_timeout_sec(
            {"verify": {"impl_code_review_timeout_sec": 900}}
        ) == 900


class TestGetImplCodeReviewConcurrency:
    """ConfigLoader.get_impl_code_review_concurrency：缺省 4（add-impl-ocr-parallel-lane D7 由 2 上调），仅正整数 int。"""

    def test_missing_verify_section(self):
        """verify 节缺失 → 4"""
        assert ConfigLoader.get_impl_code_review_concurrency({}) == 4

    def test_missing_key(self):
        """verify 存在但无该键 → 4（spec：键缺失取缺省）"""
        assert ConfigLoader.get_impl_code_review_concurrency({"verify": {}}) == 4

    def test_zero_value(self):
        """值为 0（≤0）→ 4（spec：非法值回退缺省）"""
        assert ConfigLoader.get_impl_code_review_concurrency(
            {"verify": {"impl_code_review_concurrency": 0}}
        ) == 4

    def test_negative_value(self):
        """值为 -1 → 4"""
        assert ConfigLoader.get_impl_code_review_concurrency(
            {"verify": {"impl_code_review_concurrency": -1}}
        ) == 4

    def test_string_value(self):
        """值为 "4"（字符串）→ 4"""
        assert ConfigLoader.get_impl_code_review_concurrency(
            {"verify": {"impl_code_review_concurrency": "4"}}
        ) == 4

    def test_bool_value(self):
        """值为 True（bool 不算 int）→ 4"""
        assert ConfigLoader.get_impl_code_review_concurrency(
            {"verify": {"impl_code_review_concurrency": True}}
        ) == 4

    def test_valid_positive_int(self):
        """值为 4（合法正整数）→ 4（spec：合法值透传）"""
        assert ConfigLoader.get_impl_code_review_concurrency(
            {"verify": {"impl_code_review_concurrency": 4}}
        ) == 4


class TestGetImplCodeReviewEffort:
    """ConfigLoader.get_impl_code_review_effort：缺省 "low"，枚举三值合法。"""

    def test_missing_verify_section(self):
        """verify 节缺失 → 'low'"""
        assert ConfigLoader.get_impl_code_review_effort({}) == "low"

    def test_missing_key(self):
        """verify 存在但无该键 → "low"（spec：键缺失取缺省）"""
        assert ConfigLoader.get_impl_code_review_effort({"verify": {}}) == "low"

    def test_invalid_value(self):
        """值为 "extreme"（非法枚举）→ "low"（spec：非法值回退缺省）"""
        assert ConfigLoader.get_impl_code_review_effort(
            {"verify": {"impl_code_review_effort": "extreme"}}
        ) == "low"

    def test_case_sensitive(self):
        """值为 "LOW"（大小写不匹配）→ 'low'"""
        assert ConfigLoader.get_impl_code_review_effort(
            {"verify": {"impl_code_review_effort": "LOW"}}
        ) == "low"

    def test_non_string(self):
        """值为 1（非 str）→ 'low'"""
        assert ConfigLoader.get_impl_code_review_effort(
            {"verify": {"impl_code_review_effort": 1}}
        ) == "low"

    def test_medium_value(self):
        """值为 "medium" → "medium"（合法枚举透传）"""
        assert ConfigLoader.get_impl_code_review_effort(
            {"verify": {"impl_code_review_effort": "medium"}}
        ) == "medium"

    def test_high_value(self):
        """值为 "high" → "high"（合法枚举透传）"""
        assert ConfigLoader.get_impl_code_review_effort(
            {"verify": {"impl_code_review_effort": "high"}}
        ) == "high"


class TestReadersIndependence:
    """1.4/1.5：三读取器各自独立、互不牵连；项目级覆盖用户级（深合并后）。"""

    def test_effort_invalid_does_not_affect_others(self):
        """effort 非法不应连带使 timeout_sec/concurrency 回退缺省。"""
        config = {
            "verify": {
                "impl_code_review_timeout_sec": 900,
                "impl_code_review_concurrency": 4,
                "impl_code_review_effort": "extreme",  # 非法 → 只影响自身
            }
        }
        assert ConfigLoader.get_impl_code_review_timeout_sec(config) == 900
        assert ConfigLoader.get_impl_code_review_concurrency(config) == 4
        assert ConfigLoader.get_impl_code_review_effort(config) == "low"

    def test_timeout_invalid_does_not_affect_others(self):
        """timeout_sec 非法不应连带使 concurrency/effort 回退缺省。"""
        config = {
            "verify": {
                "impl_code_review_timeout_sec": "bad",
                "impl_code_review_concurrency": 4,
                "impl_code_review_effort": "high",
            }
        }
        assert ConfigLoader.get_impl_code_review_timeout_sec(config) == 600
        assert ConfigLoader.get_impl_code_review_concurrency(config) == 4
        assert ConfigLoader.get_impl_code_review_effort(config) == "high"

    def test_project_overrides_user(self):
        """项目级覆盖用户级（合并后结果）→ 读取器返回覆盖值
        （spec：项目级覆盖用户级 Scenario，effort medium 覆盖用户级 low）。"""
        from core.config import deep_merge

        user = {
            "verify": {
                "impl_code_review_effort": "low",
                "impl_code_review_timeout_sec": 600,
            }
        }
        proj = {"verify": {"impl_code_review_effort": "medium"}}
        merged = deep_merge(user, proj)
        assert ConfigLoader.get_impl_code_review_effort(merged) == "medium"
        # 未覆盖的键仍取用户级值
        assert ConfigLoader.get_impl_code_review_timeout_sec(merged) == 600

    def test_not_in_resolve_defaults(self):
        """三键 MUST NOT 进入 resolve_config 缺省填充——键缺失时读取器回退缺省，
        且有效配置 dict 中不出现三个键（对齐 get_impl_code_review_enabled）。"""
        # 不经过文件解析的轻量断言：resolve_config 的 defaults 填充列表不含三键。
        # 直接验证 resolve_config 干跑（临时目录无配置文件）→ 有效配置无 verify 节。
        import tempfile

        # 隔离用户级配置目录：resolve_config 无条件合并 ~/.fenix/config.yaml，
        # 宿主机该文件含真实 verify.impl_code_review* 三键（本机非缺省）→ 不隔离
        # 则「有效配置 dict 不出现三键」必然假失败（home-sensitive，2026-09-22
        # 全量回归）。同款修法见 test_config.py / test_supervision_timeout_consistency.py。
        with tempfile.TemporaryDirectory() as base:
            with patch("core.config.USER_CONFIG_DIR", Path(base) / "user"):
                with tempfile.TemporaryDirectory(dir=base) as td:
                    effective = ConfigLoader.resolve_config(td)
        verify = effective.get("verify")
        assert verify is None or "impl_code_review_timeout_sec" not in verify
        assert verify is None or "impl_code_review_concurrency" not in verify
        assert verify is None or "impl_code_review_effort" not in verify
        # 读取器仍按缺省生效
        assert ConfigLoader.get_impl_code_review_timeout_sec(effective) == 600
        # 缺省 4（add-impl-ocr-parallel-lane D7：2 → 4，显式配置不受影响）
        assert ConfigLoader.get_impl_code_review_concurrency(effective) == 4
        assert ConfigLoader.get_impl_code_review_effort(effective) == "low"


# ── 7.2 runner._write_run_ocr_config 注入 timeout_sec ─────────────────


class TestWriteRunOcrConfigTimeoutInject:
    """runner._write_run_ocr_config 落盘含 timeout_sec（显式值与缺省值两例）。"""

    def _make_runner(self, proot: Path, config: dict):
        from test_agent_runner import make_runner

        runner = make_runner(proot)
        runner.config = dict(config)
        target = proot / ".fenix" / "agent-config" / "testprov"
        target.mkdir(parents=True, exist_ok=True)
        runner._ensure_agent_config_dir = lambda name, provider_model="": target
        return runner

    def test_explicit_timeout_sec_injected(self, tmp_path):
        """显式配置 timeout_sec=900 → 落盘 JSON custom_providers.fenix-impl.timeout_sec==900。"""
        runner = self._make_runner(
            tmp_path, {"verify": {"impl_code_review": True, "impl_code_review_timeout_sec": 900}}
        )
        provider = {"name": "testprov", "apikey": "k", "baseurl": "http://x"}
        home_dir = runner._write_run_ocr_config(provider, "m")
        assert home_dir is not None
        cfg = json.loads((home_dir / ".opencodereview" / "config.json").read_text(encoding="utf-8"))
        assert cfg["custom_providers"]["fenix-impl"]["timeout_sec"] == 900
        # 既有字段同批写入不受影响
        assert cfg["custom_providers"]["fenix-impl"]["url"] == "http://x"

    def test_default_timeout_sec_injected(self, tmp_path):
        """未配置 timeout_sec → 落盘 JSON timeout_sec==600（读取器缺省）。"""
        runner = self._make_runner(
            tmp_path, {"verify": {"impl_code_review": True}}
        )
        provider = {"name": "testprov", "apikey": "k", "baseurl": "http://x"}
        home_dir = runner._write_run_ocr_config(provider, "m")
        assert home_dir is not None
        cfg = json.loads((home_dir / ".opencodereview" / "config.json").read_text(encoding="utf-8"))
        assert cfg["custom_providers"]["fenix-impl"]["timeout_sec"] == 600

    def test_invalid_timeout_falls_back_to_default(self, tmp_path):
        """非法 timeout_sec（"abc"）→ 读取器回退 600，落盘不中断。"""
        runner = self._make_runner(
            tmp_path, {"verify": {"impl_code_review": True, "impl_code_review_timeout_sec": "abc"}}
        )
        provider = {"name": "testprov", "apikey": "k", "baseurl": "http://x"}
        home_dir = runner._write_run_ocr_config(provider, "m")
        assert home_dir is not None
        cfg = json.loads((home_dir / ".opencodereview" / "config.json").read_text(encoding="utf-8"))
        assert cfg["custom_providers"]["fenix-impl"]["timeout_sec"] == 600


# ── add-impl-ocr-parallel-lane 5.1：prompt_builder._ocr_findings_section ──


class TestOcrFindingsSection:
    """_ocr_findings_section：directive 文件驱动注入 / 零注入 / 处置契约文案。

    内联收尾审查段（_impl_code_review_section）已退役——收尾 ocr 由框架侧
    异步车道承载（add-impl-ocr-parallel-lane），实现者提示词只在被 join 打回
    的修复轮收到 findings 清单与 disposition 处置契约。
    """

    def _make_pb(self, tmp_path: Path, config: dict):
        from test_agent_runner import make_runner
        from core.agent_runner.prompt_builder import PromptBuilder

        runner = make_runner(tmp_path)
        runner.config = dict(config)
        return PromptBuilder(runner)

    def _write_directive(self, tmp_path: Path, findings, round_no=1):
        d = tmp_path / ".fenix" / "verify-progress" / "demo"
        d.mkdir(parents=True, exist_ok=True)
        payload = {"spec": "demo", "round": round_no, "max_rounds": 1, "findings": findings}
        (d / "ocr_findings_directive.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def test_no_directive_zero_injection(self, tmp_path):
        """directive 文件缺失 → 空串（零注入，非打回轮 prompt 逐字节不变）。"""
        pb = self._make_pb(tmp_path, {"verify": {"impl_code_review": True}})
        assert pb._ocr_findings_section("demo") == ""

    def test_directive_injects_findings_and_contract(self, tmp_path):
        """directive 存在 → 注入 findings 清单 + disposition 契约 + 重验要求。"""
        self._write_directive(
            tmp_path,
            [
                {
                    "path": "core/x.py",
                    "start_line": 12,
                    "category": "correctness",
                    "severity": "major",
                    "content": "空跑被判成功（fail-closed 缺失）",
                }
            ],
        )
        pb = self._make_pb(tmp_path, {"verify": {"impl_code_review": True}})
        section = pb._ocr_findings_section("demo")
        assert "core/x.py:12" in section
        assert "correctness" in section
        assert "空跑被判成功" in section
        # 处置契约：三值白名单 + rejected/deferred 须附非空 reason
        assert '"disposition"' in section
        assert '"fixed"' in section and '"rejected"' in section and '"deferred"' in section
        assert "非空" in section
        # 处置登记路径为 worktree 相对路径，MUST NOT 出现主树绝对路径字样
        assert ".fenix/verify-progress/demo/code-review.json" in section
        assert str(tmp_path) not in section
        # 修码后重验：定向测试 + 全量回归有界入口前台直跑
        assert "bin/run_full_suite.py" in section
        assert "定向测试" in section
        # 实现者不再自跑 ocr
        assert "MUST NOT" in section and "自己跑 ocr" in section

    def test_round_counter_injected(self, tmp_path):
        """round 字段注入修复轮次与上限语义（达上限转台账提示）。"""
        self._write_directive(tmp_path, [{"path": "a.py", "content": "x"}], round_no=1)
        pb = self._make_pb(tmp_path, {})
        section = pb._ocr_findings_section("demo")
        assert "第 1 轮" in section
        assert "上限" in section

    def test_corrupt_directive_zero_injection(self, tmp_path):
        """directive 非法 JSON / findings 非列表 → 空串（fail-open 零注入）。"""
        d = tmp_path / ".fenix" / "verify-progress" / "demo"
        d.mkdir(parents=True, exist_ok=True)
        (d / "ocr_findings_directive.json").write_text("{not-json", encoding="utf-8")
        pb = self._make_pb(tmp_path, {})
        assert pb._ocr_findings_section("demo") == ""
        (d / "ocr_findings_directive.json").write_text(
            json.dumps({"findings": "nope"}), encoding="utf-8"
        )
        assert pb._ocr_findings_section("demo") == ""

    def test_empty_findings_zero_injection(self, tmp_path):
        """findings 空列表 → 空串（无义务可注入）。"""
        self._write_directive(tmp_path, [])
        pb = self._make_pb(tmp_path, {})
        assert pb._ocr_findings_section("demo") == ""


class TestGetImplCodeReviewMode:
    """get_impl_code_review_mode（add-impl-ocr-parallel-lane 1.1）：缺省 gate，
    仅接受 gate/advisory 白名单，非法值回退缺省。"""

    def test_missing_verify_section(self):
        """verify 节缺失 → 'gate'"""
        assert ConfigLoader.get_impl_code_review_mode({}) == "gate"

    def test_missing_key(self):
        """verify 存在但无该键 → 'gate'（缺省）"""
        assert ConfigLoader.get_impl_code_review_mode({"verify": {}}) == "gate"

    def test_gate_value(self):
        """值为 'gate' → 'gate'（合法透传）"""
        assert (
            ConfigLoader.get_impl_code_review_mode({"verify": {"impl_code_review_mode": "gate"}})
            == "gate"
        )

    def test_advisory_value(self):
        """值为 'advisory' → 'advisory'（合法透传）"""
        assert (
            ConfigLoader.get_impl_code_review_mode(
                {"verify": {"impl_code_review_mode": "advisory"}}
            )
            == "advisory"
        )

    def test_invalid_value_falls_back(self):
        """值为 'strict'（白名单外）→ 'gate'（fail-open 回退）"""
        assert (
            ConfigLoader.get_impl_code_review_mode({"verify": {"impl_code_review_mode": "strict"}})
            == "gate"
        )

    def test_case_sensitive(self):
        """值为 'GATE'（大小写不匹配）→ 'gate'"""
        assert (
            ConfigLoader.get_impl_code_review_mode({"verify": {"impl_code_review_mode": "GATE"}})
            == "gate"
        )

    def test_non_string_value(self):
        """值为 1（非 str）→ 'gate'"""
        assert ConfigLoader.get_impl_code_review_mode({"verify": {"impl_code_review_mode": 1}}) == "gate"

    def test_empty_string_value(self):
        """值为 ''（空串）→ 'gate'"""
        assert ConfigLoader.get_impl_code_review_mode({"verify": {"impl_code_review_mode": ""}}) == "gate"


class TestGetImplCodeReviewLaneTimeoutSec:
    """get_impl_code_review_lane_timeout_sec（add-impl-ocr-parallel-lane 1.1b）：
    车道级硬超时，缺省 2400，与单请求超时键按键分离，仅正整数 int。"""

    def test_missing_verify_section(self):
        """verify 节缺失 → 2400"""
        assert ConfigLoader.get_impl_code_review_lane_timeout_sec({}) == 2400

    def test_missing_key(self):
        """verify 存在但无该键 → 2400（缺省）"""
        assert ConfigLoader.get_impl_code_review_lane_timeout_sec({"verify": {}}) == 2400

    def test_valid_positive_int(self):
        """值为 3600（合法正整数）→ 3600"""
        assert (
            ConfigLoader.get_impl_code_review_lane_timeout_sec(
                {"verify": {"impl_code_review_lane_timeout_sec": 3600}}
            )
            == 3600
        )

    def test_zero_and_negative(self):
        """0 / -1（≤0）→ 2400（非法回退缺省）"""
        for bad in (0, -1):
            assert (
                ConfigLoader.get_impl_code_review_lane_timeout_sec(
                    {"verify": {"impl_code_review_lane_timeout_sec": bad}}
                )
                == 2400
            )

    def test_string_value(self):
        """值为 "3000"（字符串）→ 2400"""
        assert (
            ConfigLoader.get_impl_code_review_lane_timeout_sec(
                {"verify": {"impl_code_review_lane_timeout_sec": "3000"}}
            )
            == 2400
        )

    def test_bool_value(self):
        """值为 True（bool 不算 int）→ 2400"""
        assert (
            ConfigLoader.get_impl_code_review_lane_timeout_sec(
                {"verify": {"impl_code_review_lane_timeout_sec": True}}
            )
            == 2400
        )

    def test_independent_of_request_timeout(self):
        """按键分离：车道超时键设置不影响单请求超时键，反之亦然。"""
        config = {
            "verify": {
                "impl_code_review_timeout_sec": 900,
                "impl_code_review_lane_timeout_sec": 3600,
            }
        }
        assert ConfigLoader.get_impl_code_review_timeout_sec(config) == 900
        assert ConfigLoader.get_impl_code_review_lane_timeout_sec(config) == 3600
