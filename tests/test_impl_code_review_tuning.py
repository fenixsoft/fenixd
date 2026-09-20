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
    """ConfigLoader.get_impl_code_review_concurrency：缺省 2，仅正整数 int。"""

    def test_missing_verify_section(self):
        """verify 节缺失 → 2"""
        assert ConfigLoader.get_impl_code_review_concurrency({}) == 2

    def test_missing_key(self):
        """verify 存在但无该键 → 2（spec：键缺失取缺省）"""
        assert ConfigLoader.get_impl_code_review_concurrency({"verify": {}}) == 2

    def test_zero_value(self):
        """值为 0（≤0）→ 2（spec：非法值回退缺省）"""
        assert ConfigLoader.get_impl_code_review_concurrency(
            {"verify": {"impl_code_review_concurrency": 0}}
        ) == 2

    def test_negative_value(self):
        """值为 -1 → 2"""
        assert ConfigLoader.get_impl_code_review_concurrency(
            {"verify": {"impl_code_review_concurrency": -1}}
        ) == 2

    def test_string_value(self):
        """值为 "4"（字符串）→ 2"""
        assert ConfigLoader.get_impl_code_review_concurrency(
            {"verify": {"impl_code_review_concurrency": "4"}}
        ) == 2

    def test_bool_value(self):
        """值为 True（bool 不算 int）→ 2"""
        assert ConfigLoader.get_impl_code_review_concurrency(
            {"verify": {"impl_code_review_concurrency": True}}
        ) == 2

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
        # 直接验证 resolve_config 干跑（临时目录无配置文件）→ 有效配置无 verify 节
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            effective = ConfigLoader.resolve_config(td)
        verify = effective.get("verify")
        assert verify is None or "impl_code_review_timeout_sec" not in verify
        assert verify is None or "impl_code_review_concurrency" not in verify
        assert verify is None or "impl_code_review_effort" not in verify
        # 读取器仍按缺省生效
        assert ConfigLoader.get_impl_code_review_timeout_sec(effective) == 600
        assert ConfigLoader.get_impl_code_review_concurrency(effective) == 2
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


# ── 7.3 / 7.3b prompt_builder._impl_code_review_section ─────────────────


class TestImplCodeReviewSection:
    """_impl_code_review_section 命令串注入 / 零注入 / 文案一致性。"""

    def _make_pb(self, tmp_path: Path, config: dict):
        from test_agent_runner import make_runner
        from core.agent_runner.prompt_builder import PromptBuilder

        runner = make_runner(tmp_path)
        runner.config = dict(config)
        return PromptBuilder(runner)

    def test_injects_concurrency_and_effort_explicit(self, tmp_path):
        """显式 concurrency=3 / effort="medium" → 命令串含 --concurrency 3 --effort medium。"""
        pb = self._make_pb(
            tmp_path,
            {
                "verify": {
                    "impl_code_review": True,
                    "impl_code_review_concurrency": 3,
                    "impl_code_review_effort": "medium",
                }
            },
        )
        section = pb._impl_code_review_section("demo")
        assert "--concurrency 3" in section
        assert "--effort medium" in section
        # 既有串保持不变
        assert "--format json --output /tmp/ocr-raw.json" in section
        assert "bin/ocr_review.py review --from <base> --to HEAD" in section

    def test_injects_defaults(self, tmp_path):
        """未配置 concurrency/effort → 命令串含缺省 --concurrency 2 --effort low。"""
        pb = self._make_pb(tmp_path, {"verify": {"impl_code_review": True}})
        section = pb._impl_code_review_section("demo")
        assert "--concurrency 2" in section
        assert "--effort low" in section

    def test_no_max_tokens_budget(self, tmp_path):
        """命令示例串 MUST NOT 含 --max-tokens-budget（可执行的注入命令不得带
        该 flag）；成本控制条的「MUST NOT 传」禁止性文案保留（任务 3.2 要求
        保持既有约束文案——那是说明文字，不是可执行命令）。"""
        pb = self._make_pb(
            tmp_path,
            {"verify": {"impl_code_review": True, "impl_code_review_effort": "high"}},
        )
        section = pb._impl_code_review_section("demo")
        # 命令示例行（含 bin/ocr_review.py review 的那一行）不得含该 flag
        for line in section.splitlines():
            if "bin/ocr_review.py review" in line:
                assert "--max-tokens-budget" not in line
        # 成本控制条保留「MUST NOT 传 --max-tokens-budget」既有约束文案
        assert "MUST NOT 传 `--max-tokens-budget`" in section

    def test_switch_off_zero_injection(self, tmp_path):
        """开关关闭 → 段为空串，且不调用 concurrency/effort 两读取器
        （patch 两读取器抛 AssertionError——被调用即失败）。"""
        from core.config import ConfigLoader

        pb = self._make_pb(tmp_path, {"verify": {"impl_code_review": False}})
        with patch.object(
            ConfigLoader, "get_impl_code_review_concurrency",
            side_effect=AssertionError("MUST NOT call concurrency when disabled"),
        ), patch.object(
            ConfigLoader, "get_impl_code_review_effort",
            side_effect=AssertionError("MUST NOT call effort when disabled"),
        ):
            section = pb._impl_code_review_section("demo")
        assert section == ""

    def test_switch_missing_zero_injection(self, tmp_path):
        """开关键缺失 → 段为空串（fail-open，不注入）。"""
        pb = self._make_pb(tmp_path, {"verify": {}})
        assert pb._impl_code_review_section("demo") == ""

    def test_cost_control_wording_no_self_effort_choice(self, tmp_path):
        """7.3b：改写后的成本控制文案与新命令示例不冲突——段内不得再出现
        「自行选择 effort」类措辞（防注入值被实现者覆盖的回归）。"""
        pb = self._make_pb(
            tmp_path,
            {"verify": {"impl_code_review": True, "impl_code_review_effort": "low"}},
        )
        section = pb._impl_code_review_section("demo")
        # 不得再出现「改用 --effort low|medium|high 控制」类自我选择措辞
        assert "改用 `--effort low|medium|high`" not in section
        # 不得出现「自行选择」与 effort 相邻的自我选择措辞（命令形态微调
        # 用「按改动规模自行选择」仍允许——那指 --from/--to/--commit/工作区模式）
        assert "自行选择 `--effort" not in section
        assert "自行选择 --effort" not in section
        assert "自行选择 effort" not in section
        # 新文案应声明框架已注入 + MUST NOT 自行改写
        assert "已由框架经" in section
        assert "MUST NOT 自行改写" in section
        # 用户可配置键名出现在文案中（可调性说明保留）
        assert "verify.impl_code_review_effort" in section
        assert "verify.impl_code_review_concurrency" in section

    def test_effort_injected_value_consistent_with_section(self, tmp_path):
        """命令串中的 effort 取值与「用户可配置」声明的键一致——注入值出现于命令。"""
        pb = self._make_pb(
            tmp_path,
            {"verify": {"impl_code_review": True, "impl_code_review_effort": "high"}},
        )
        section = pb._impl_code_review_section("demo")
        assert "--effort high" in section
        assert "--concurrency 2" in section  # 未配置并发 → 缺省注入