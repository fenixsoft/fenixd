"""fix-robustness-edge-cases 3.2/3.4：结构化日志不得有旁路写丢。

- 3.2 静态扫描 core：断言无裸 ``logging.getLogger(...)``（``fenixd`` 层级除外）——
  用 tokenize 精确识别代码（非注释/字符串）中的 getLogger 调用，防新引入旁路。
- 3.3 级联断言：Debug 行为随 logging.level 生效（INFO 实例 DEBUG 不落盘、
  DEBUG 实例 DEBUG 落盘），修复 handle() 绕过 isEnabledFor 的问题。
- 3.4 实证：「持久化集加载净化剔除」告警经 fenixd.verify_scenarios 传播后
  出现在 fenixd.log。
"""

import io
import json
import logging
import sys
import tokenize
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FENIXD_LOGGER_RE = (
    '"fenixd'
)


def _iter_core_py_files():
    core_root = Path(__file__).resolve().parents[1] / "core"
    for p in sorted(core_root.rglob("*.py")):
        yield p


def _getlogger_calls(src: str):
    """返回 [(行号, 首个参数文本)] —— 代码中 getLogger 调用的位置清单。

    基于 tokenize（注释/字符串/文档中的 getLogger 不产生 NAME token，天然跳过）。
    """
    calls = []
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, UnicodeDecodeError):
        return calls
    for i, tok in enumerate(toks):
        if tok.type != tokenize.NAME or tok.string != "getLogger":
            continue
        # getLogger( —— 下一个有意义的 token 必须是 "("
        j = i + 1
        while j < len(toks) and toks[j].type in (tokenize.NL,):
            j += 1
        if j >= len(toks) or toks[j].string != "(":
            continue
        # 取第一个参数 token：字符串字面量或 __name__ 之类 NAME
        k = j + 1
        while k < len(toks) and toks[k].type in (tokenize.NL, tokenize.NEWLINE):
            k += 1
        if k < len(toks):
            calls.append((tok.start[0], toks[k].string))
        else:
            calls.append((tok.start[0], None))
    return calls


def _is_allowed_arg(arg: str) -> bool:
    """允许的 getLogger 参数：fenixd 层级字符串字面量（可传播到已挂载 handler）。

    ``getLogger(__name__)``（core 模块 ``__name__`` 恒为 ``core.*``，非 fenixd
    层级）与任意其它名称均为旁路，禁止。
    """
    if arg is None:
        return False
    return arg.startswith('"fenixd') or arg.startswith("'fenixd")


class TestNoBareGetLogger:
    def test_no_bare_getlogger_in_core(self):
        violations = []
        for p in _iter_core_py_files():
            src = p.read_text(encoding="utf-8")
            for lineno, arg in _getlogger_calls(src):
                if not _is_allowed_arg(arg):
                    violations.append(f"{p}:{lineno} getLogger({arg!r})")
        assert violations == [], (
            "core/ 存在旁路 getLogger（MUST 用 fenixd. 可传播层级）:\n"
            + "\n".join(violations)
        )


class TestLoggerLevelRespected:
    """3.3：Logger._log 不得绕过 isEnabledFor（修复前 DEBUG 恒落盘）。"""

    def test_debug_not_written_when_info_level(self, tmp_path):
        from core.logger import Logger

        log_dir = tmp_path / "logs"
        logger = Logger(log_dir, "INFO")
        try:
            logger.debug("comp", "should-not-appear-debug-line")
            logger.info("comp", "should-appear-info-line")
            logger.close()
            text = (log_dir / "fenixd.log").read_text(encoding="utf-8")
            assert "should-not-appear-debug-line" not in text, "INFO 级别下 DEBUG 不得落盘"
            assert "should-appear-info-line" in text
        finally:
            logger.close()

    def test_debug_written_when_debug_level(self, tmp_path):
        from core.logger import Logger

        log_dir = tmp_path / "logs-debug"
        logger = Logger(log_dir, "DEBUG")
        try:
            logger.debug("comp", "should-appear-debug-line")
            logger.close()
            text = (log_dir / "fenixd.log").read_text(encoding="utf-8")
            assert "should-appear-debug-line" in text, "DEBUG 级别下 DEBUG 正常落盘"
        finally:
            logger.close()


class TestWarningReachesFenixdLog:
    """3.4 实证：持久化集加载净化剔除类告警出现在 fenixd.log。"""

    def test_verify_scenarios_purge_warning_lands(self, tmp_path):
        from core.logger import Logger
        from core.verify_scenarios import load_scenario_set

        log_dir = tmp_path / "logs"
        logger = Logger(log_dir, "INFO")
        try:
            proot = tmp_path / "proj"
            spec = "demo-spec"
            vp = proot / ".fenix" / "verify-progress" / spec
            vp.mkdir(parents=True)
            (vp / "scenarios.json").write_text(
                json.dumps({
                    "spec": spec,
                    "scenarios": [
                        {"id": "sc-ok", "kind": "web"},
                        {"id": "sc-orphan"},  # 缺 kind → 净化剔除 WARNING
                    ],
                }),
                encoding="utf-8",
            )
            ss = load_scenario_set(proot, spec)
            assert ss is not None, "净化后集合仍返回"
            logger.close()  # flush + 关 handler，确保落盘
        finally:
            logger.close()
        text = (log_dir / "fenixd.log").read_text(encoding="utf-8")
        assert "持久化集加载净化剔除" in text, "净化剔除 WARNING 必须落入 fenixd.log"
        assert "sc-orphan" in text, "剔除 id 清单出现在日志"