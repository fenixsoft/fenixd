"""failure_model.py — run 失败建模与归因分类单源（fix-spawn-attribution-hardening D2/A4）。

现状把一切 run 异常都按可重试处理（通用重试链：秒挂计数 → 瞬断判定 →
原地退避 → 换候选 → attempt 烧尽 → dispatch 通用重派 → 同因熔断冻结 →
arbiter 升级）——确定性 spawn 缺件（claude 不在 PATH）同样走全链，恰是
v0.1.1 Windows 部署实录「预检放行、spawn 必败、三连烧」根因。本模块提供：

- **确定性失败分类**：spawn 阶段 ``FileNotFoundError``（errno 2/3，环境
  缺件）→ infra-deterministic 终态——部署态不会秒级自愈，重试无意义，
  一跳收口（不重试、不冻结、不升级）；
- **终态错误文案单源**：``[infra-deterministic]`` 前缀标记（对齐
  ``[retry-yielded]`` / ``[run-stall-budget]`` 的「前缀即语义标签」约定）
  + 根因 + 修复指引；dispatch 终态分类（``_classify_run_terminal_failure``）
  按标记路由持态分支；
- **归因三型分立**：``spawn_failed`` / ``nonzero_exit`` / ``result_missing``
  枚举与纯函数分类器；
- **result_missing 取证**：归因附 run 转录 stderr 尾窗（截尾 2KB）——
  v0.1.1 实测 stderr_tail 为空串导致取证断链的修复面。

纯逻辑层：不 import runner/pm_engine；转录读取函数接受路径参数，测试用
tmp_path 注入。runner/dispatch 两侧消费同一分类（分类表挂在 core/agent_runner
失败建模处，design D2）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Sequence, Union

# ── 归因三型枚举（design D2：run 失败归因 MUST 三型分立）──────────────

RUN_ATTRIBUTION_SPAWN_FAILED = "spawn_failed"
RUN_ATTRIBUTION_NONZERO_EXIT = "nonzero_exit"
RUN_ATTRIBUTION_RESULT_MISSING = "result_missing"

RUN_ATTRIBUTION_TYPES = (
    RUN_ATTRIBUTION_SPAWN_FAILED,
    RUN_ATTRIBUTION_NONZERO_EXIT,
    RUN_ATTRIBUTION_RESULT_MISSING,
)

# result_missing 归因文本前缀标记（前缀即语义标签约定，供终态记录机械识别）
RESULT_MISSING_ATTRIBUTION_TAG = "[result-missing]"

# ── 确定性失败（infra-deterministic）─────────────────────────────────

# 终态 error 前缀标记：dispatch 终态分类按本标记路由「持态 + 预算退款 +
# 不重派 + 不升级」分支（_classify_run_terminal_failure 消费）。
INFRA_DETERMINISTIC_ERROR_MARKER = "[infra-deterministic]"

# spawn 缺件的确定性 errno 闭集：ENOENT(2)/ENOEXEC 族目录缺失(3)。
# WinError 2/3 即此映射（部署实录形态）。errno 3 仅 Windows
# （ERROR_PATH_NOT_FOUND）；POSIX 恒 ENOENT(2)，该值在 Linux 不出现。
DETERMINISTIC_SPAWN_ERRNOS = frozenset({2, 3})

# result_missing 归因 stderr 尾窗截尾（design D2：截尾 2KB）
STDERR_TAIL_WINDOW_LIMIT = 2048

_SPAWN_REPAIR_HINT = (
    "按 install.md §8 服务 PATH 最小集补齐 PATH（或 install_unit env= 注入"
    " AppEnvironmentExtra）后 nssm restart 服务"
)

# cwd 目录缺失形态（errno 2 的另一根因 / errno 3 恒此形态）的修复指引：
# FileNotFoundError(errno 2) 在 Popen 触发面不限于可执行文件缺失——cwd=
# 指向不存在的目录（如实现 worktree 被外部清理）时 chdir 阶段同样抛
# errno 2；errno 3（仅 Windows ERROR_PATH_NOT_FOUND）则恒为目录缺失。
_CWD_REPAIR_HINT = (
    "核查 spawn cwd 目录是否存在（如实现 worktree 被外部清理后未重建）"
)


def is_deterministic_spawn_failure(exc: Optional[BaseException]) -> bool:
    """spawn 阶段 ``FileNotFoundError``（errno 2/3）＝环境缺件，确定性失败。

    环境缺件（可执行文件/目录不存在）属部署态缺陷，不会秒级自愈——重试
    无意义。PermissionError（存在但不可执行）不在闭集：权限问题可被人工
    现场修复且属罕见形态，维持既有重试语义，不扩面（design D2 口径）。
    """
    if not isinstance(exc, FileNotFoundError):
        return False
    return getattr(exc, "errno", None) in DETERMINISTIC_SPAWN_ERRNOS


def infra_deterministic_error(
    executable: Optional[str], exc: Optional[BaseException] = None
) -> str:
    """确定性 spawn 失败的终态 error 文案（标记 + 根因 + 修复指引）。

    STATE error 字段按本文案落盘（Requirement：MUST 带根因与修复指引）；
    前缀标记供 dispatch 终态分类机械识别。文案按 exc errno 细分归因：
    errno 3（Windows）恒为目录缺失形态；errno 2 并列 PATH 缺件与 spawn
    cwd 目录缺失两根因（两种形态终态分类相同，仅修复指引不同）。
    """
    exe = str(executable) if executable else "harness CLI"
    reason = f"：{exc}" if exc is not None else ""
    # 按形态细分归因（errno 3 恒目录缺失，见 DETERMINISTIC_SPAWN_ERRNOS
    # 注；errno 2 两可）：避免运维按 PATH 指引排查目录缺失问题。
    if getattr(exc, "errno", None) == 3:
        cause = f"spawn 目录不存在（errno 3，目录缺失）：{exe}"
        repair = _CWD_REPAIR_HINT
    else:
        cause = f"{exe} 不在当前 PATH，或 spawn cwd 目录缺失"
        repair = f"{_SPAWN_REPAIR_HINT}；{_CWD_REPAIR_HINT}"
    return (
        f"{INFRA_DETERMINISTIC_ERROR_MARKER} spawn 失败（环境缺件，确定性）："
        f"{cause}{reason}——{repair}；"
        f"本失败为终态：不消耗实现预算、不自动重试、不升级仲裁。"
    )


# ── 归因三型分类器（纯函数）──────────────────────────────────────────


def classify_run_failure(
    exc: Optional[BaseException] = None,
    *,
    exit_code: Optional[int] = None,
    has_result: Optional[bool] = None,
) -> str:
    """run 失败归因三型分立单源（spawn 失败 / 非零退出 / 结果文件缺失）。

    判定序：确定性 spawn 缺件 → ``spawn_failed``；结果文件未产出
    （``has_result is False``，run 异常结束形态）→ ``result_missing``；
    其余（进程已起且异常退出/超时击杀等）→ ``nonzero_exit``。
    """
    if is_deterministic_spawn_failure(exc):
        return RUN_ATTRIBUTION_SPAWN_FAILED
    if has_result is False:
        return RUN_ATTRIBUTION_RESULT_MISSING
    return RUN_ATTRIBUTION_NONZERO_EXIT


# ── result_missing 取证：run 转录 stderr 尾窗（截尾 2KB）──────────────


def stderr_tail_window(
    lines: Optional[Sequence[Union[str, bytes]]],
    limit: int = STDERR_TAIL_WINDOW_LIMIT,
) -> str:
    """stderr 行序列 → 尾窗文本（UTF-8 编码截尾 ``limit`` 字节，防劈字容错）。

    bytes 行按 UTF-8 解码（errors=replace），不做 repr 字符串化。
    """
    if not lines:
        return ""
    text_lines = [
        ln.decode("utf-8", errors="replace") if isinstance(ln, bytes) else ln
        for ln in lines
    ]
    text = "\n".join(
        line.rstrip() for line in text_lines if line.strip()
    )
    if not text:
        return ""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) > limit:
        encoded = encoded[-limit:]
        # 尾窗起点可能劈开多字节字符：回退到合法字符边界（跳过 UTF-8
        # 续字节 10xxxxxx）而非替换符——替换符重编码会再膨胀超限
        i = 0
        while i < len(encoded) and (encoded[i] & 0xC0) == 0x80:
            i += 1
        encoded = encoded[i:]
    return encoded.decode("utf-8", errors="replace").lstrip("\n")


def transcript_stderr_tail(
    run_file, limit: int = STDERR_TAIL_WINDOW_LIMIT
) -> str:
    """读 run 转录 jsonl 中 ``type=stderr`` 行，取尾窗（result_missing 附证）。

    转录缺席/损坏/无 stderr 行返回空串（fail-open——归因主体仍带 error
    文本，取证面尽力而为）。
    """
    lines: list = []
    try:
        with open(run_file, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                try:
                    entry = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(entry, dict) and entry.get("type") == "stderr":
                    line = entry.get("line")
                    if line:
                        lines.append(str(line))
    except OSError:
        return ""
    return stderr_tail_window(lines, limit)


def result_missing_attribution(
    final_error: Optional[str],
    stderr_tail: Optional[str] = "",
    run_file=None,
    limit: int = STDERR_TAIL_WINDOW_LIMIT,
) -> str:
    """result_missing 归因文本（类型标记 + error + stderr 尾窗）。

    v0.1.1 实测 stderr_tail 为空串（取证断链）：摘要缺位时回读 run 转录
    （``run_file``）提取 stderr 尾窗，仍缺位则如实省略（不伪造非空串）。
    """
    tail = (stderr_tail or "").strip()
    if not tail and run_file is not None:
        tail = transcript_stderr_tail(run_file, limit)
    parts = [f"{RESULT_MISSING_ATTRIBUTION_TAG} 结果文件缺失（run 异常结束"
             "且未产出收工结果，attribution=result_missing）"]
    if final_error:
        parts.append(f"error: {str(final_error)[:200]}")
    if tail:
        parts.append(f"stderr 尾窗: {tail}")
    return "；".join(parts)


def latest_transcript_for_run(runs_dir, run_id: str) -> Optional[Path]:
    """按基础 run id 定位最新转录文件（attempt/-r 瞬态重试子文件含）。

    dispatch 侧无 sub_run_id（attempt 环内部概念），按前缀 glob + mtime
    取最新；无匹配返回 None（调用方 fail-open）。
    """
    if not run_id:
        return None
    try:
        candidates = sorted(
            Path(runs_dir).glob(f"{run_id}*.jsonl"),
            key=lambda p: p.stat().st_mtime,
        )
    except OSError:
        return None
    return candidates[-1] if candidates else None
