"""提示词占位符残留双通道判别测试（evo-improve-placeholder-scan-discrimination）。

覆盖 spec 全部 Scenario：
- 全车道回归（Scenario 4）：AGENT_TYPES 全集真实构建渲染 → 模板通道零漂移；
- 回潮拦截（Scenario 3）：模板塞回未填充占位符（{epoch} 案回潮形态）→
  渲染期 WARNING，消息含模板名与调用点；
- 模板真漂移 / 注入值字面量判别（Scenario 1/2）：缺键 WARNING 含模板名，
  注入值携带 {xxx} 字面量无 WARNING 仅 INFO 计数。

复用 test_agent_prompt_files 的 make_runner + AGENT_TYPES 参数化手法
（不复刻 values 字面量——会与实现漂移），驱动真实构建器而非桩。
"""

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import prompt_builder as pb_module
from core.agent_runner.prompt_builder import (
    AGENT_PROMPT_FILES,
    _fill_and_scan_placeholders,
)
from test_agent_runner import make_runner


AGENT_TYPES = list(AGENT_PROMPT_FILES.keys())

# 扫描器结构化日志器（与 prompt_builder 模块内 _logger 同名）
_SCAN_LOGGER = "fenixd.agent_runner.prompt_builder"

# 走统一收尾 _fill_placeholders 的主路径车道（label="spec"）；其余四条
# 独立构建路径用默认 label="run_id"（context_id 传 run token/spec_name 槽位）。
_MAIN_PATH_LANES = set(AGENT_TYPES) - {"self-review", "evolution", "code-review", "code-fix"}


def _mk_spec_dir(proot: Path, name: str) -> None:
    d = proot / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 do it\n", encoding="utf-8")


def _scan_records(caplog, level: int) -> list:
    """按精确级别过滤扫描器日志记录（WARNING 不落入 INFO 通道断言）。"""
    return [
        r for r in caplog.records
        if r.name == _SCAN_LOGGER and r.levelno == level
    ]


# ── 渲染断言：真实构建器遍历 AGENT_TYPES 全集（任务 2.1）──────────────


class TestRenderZeroTemplateDrift:
    """Scenario 4「全车道回归」：真实构建渲染后模板通道零残留。"""

    @pytest.mark.parametrize("agent_type", AGENT_TYPES)
    def test_real_render_no_drift_warning(self, tmp_path, caplog, agent_type):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        with caplog.at_level(logging.WARNING, logger=_SCAN_LOGGER):
            runner._prompt_builder._build_prompt("demo", agent_type)
        drift = [
            r for r in _scan_records(caplog, logging.WARNING)
            if "提示词占位符未解析" in r.getMessage()
        ]
        assert drift == [], (
            f"{agent_type} 模板通道真漂移: {[r.getMessage() for r in drift]}"
        )

    def test_real_render_placeholder_tokens_absent(self, tmp_path):
        """渲染后无未解析 {snake_case} 占位符 token（双通道判别不改变填充行为）。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        for agent_type in AGENT_TYPES:
            prompt = runner._prompt_builder._build_prompt("demo", agent_type)
            leftover = sorted(
                set(pb_module._PLACEHOLDER_RE.findall(prompt))
                - {"{epoch}"}  # 文档性字面量不在其列，{epoch} 案已修复不应再现
            )
            assert not leftover, f"{agent_type} 渲染残留占位符: {leftover}"


# ── 回潮拦截：模板真漂移 → WARNING 含模板名与调用点（任务 2.1/2.2）────


class TestRegressionInterception:
    """Scenario 3「回潮拦截」：模板缺键渲染期 WARNING，可直达模板文件。"""

    @pytest.mark.parametrize("agent_type", AGENT_TYPES)
    def test_unfilled_template_placeholder_warns_with_template_name(
            self, tmp_path, caplog, monkeypatch, agent_type):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        monkeypatch.setattr(
            pb_module.PromptBuilder, "_load_agent_template",
            lambda self, atype: "未填充占位符模板 {epoch}\n")
        runner = make_runner(proot)
        with caplog.at_level(logging.INFO, logger=_SCAN_LOGGER):
            runner._prompt_builder._build_prompt("demo", agent_type)
        warns = [
            r for r in _scan_records(caplog, logging.WARNING)
            if "提示词占位符未解析" in r.getMessage()
        ]
        assert warns, f"{agent_type} 模板缺键未触发 WARNING"
        msg = warns[0].getMessage()
        # 消息含模板名（AGENT_PROMPT_FILES[agent_type] 导出）——可直达模板文件
        assert AGENT_PROMPT_FILES[agent_type] in msg, f"WARNING 缺模板名: {msg}"
        # 消息含调用点 label/context_id：主路径 spec=<spec_name>，
        # 独立路径 run_id=<token>
        label = "spec" if agent_type in _MAIN_PATH_LANES else "run_id"
        assert f"{label}=demo" in msg, f"WARNING 缺调用点 {label}: {msg}"
        # 漂移键在消息里可辨识
        assert "{epoch}" in msg, f"WARNING 缺漂移键: {msg}"


# ── 判别行为单测：模板缺键 vs 注入值字面量（任务 2.2）────────────────


class TestChannelDiscrimination:
    """Scenario 1/2：双通道判别行为——真漂移 WARNING、注入字面量仅 INFO。"""

    def test_template_missing_key_warns_with_template_name(self, caplog):
        """通道一：模板骨架引用未填充占位符 → WARNING 且消息含模板名。"""
        with caplog.at_level(logging.INFO, logger=_SCAN_LOGGER):
            out = _fill_and_scan_placeholders(
                "分析对象 {spec_name} 与 {pending_entries}",
                {"{spec_name}": "demo"},
                "evolution",
                "run-1",
                template_name=AGENT_PROMPT_FILES["evolution"],
            )
        warns = [
            r for r in _scan_records(caplog, logging.WARNING)
            if "提示词占位符未解析" in r.getMessage()
        ]
        assert len(warns) == 1, f"应恰一条模板漂移 WARNING: {[r.getMessage() for r in warns]}"
        msg = warns[0].getMessage()
        assert "evolution.md" in msg, f"WARNING 缺模板名: {msg}"
        assert "agent=evolution" in msg
        assert "run_id=run-1" in msg
        assert "{pending_entries}" in msg
        # 填充行为无条件 return out（不阻断派发）
        assert "demo" in out and "{pending_entries}" in out

    def test_injected_value_literals_no_warning_only_info(self, caplog):
        """通道二：注入值携带 {xxx} 字面量 → 无 WARNING，仅 INFO 计数。"""
        injected = (
            "台账引用源码 f-string「{e}」与 URL 模板「&doc=${doc}」，"
            "均为注入值合法引用字面量"
        )
        with caplog.at_level(logging.INFO, logger=_SCAN_LOGGER):
            out = _fill_and_scan_placeholders(
                "修复以下条目：{items}",
                {"{items}": injected},
                "code-fix",
                "run-2",
                template_name=AGENT_PROMPT_FILES["code-fix"],
            )
        assert not [
            r for r in _scan_records(caplog, logging.WARNING)
            if "提示词占位符未解析" in r.getMessage()
        ], "注入值字面量不得打 WARNING"
        infos = [r for r in _scan_records(caplog, logging.INFO) if "count=" in r.getMessage()]
        assert infos, "注入值字面量应记 INFO 计数"
        msg = infos[0].getMessage()
        assert "code-fix.md" in msg and "agent=code-fix" in msg
        assert "count=2" in msg, f"INFO 应计 2 个字面量（{e}/{doc}）: {msg}"
        # 注入内容原样保留（单趟填充不二次替换）
        assert "{e}" in out and "&doc=${doc}" in out

    def test_literal_in_template_but_filled_is_not_drift(self, caplog):
        """模板占位符已被 values 覆盖 → 两通道均零告警（扣除 values 键集）。"""
        with caplog.at_level(logging.INFO, logger=_SCAN_LOGGER):
            _fill_and_scan_placeholders(
                "条目 {items} 落盘 {out_path}",
                {"{items}": "A", "{out_path}": "/tmp/x.jsonl"},
                "code-review",
                "run-3",
                template_name=AGENT_PROMPT_FILES["code-review"],
            )
        assert not _scan_records(caplog, logging.WARNING), "零漂移不应打 WARNING"
        assert not _scan_records(caplog, logging.INFO), "零漂移不应产生 INFO 计数"

    def test_default_template_name_degrades_to_legacy_behavior(self, caplog):
        """template_name 缺省 None → 退化为单通道现行为（潜在调用方零破坏）。"""
        with caplog.at_level(logging.INFO, logger=_SCAN_LOGGER):
            _fill_and_scan_placeholders("x {legacy_key}", {}, "custom-agent", "ctx")
        warns = [
            r for r in _scan_records(caplog, logging.WARNING)
            if "提示词占位符未解析" in r.getMessage()
        ]
        assert len(warns) == 1, "缺省退化路径应保留 WARNING"
        assert "template=" not in warns[0].getMessage(), (
            "退化路径无模板名可用，消息不应含 template= 字段"
        )
        assert not _scan_records(caplog, logging.INFO), "退化路径不做 INFO 通道"


if __name__ == "__main__":
    import unittest
    unittest.main()
