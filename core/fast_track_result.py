"""fast_track_result.py — fast-track 统一结果文件解析（add-fast-track-mode / D4）。

fast-track run 复用现有 ``.fenix-run-result.json`` 机制，在其中增加验证段：

    {
      "status": "success" | "error",
      "spec": "<spec>",
      "mode": "fast-track",
      "summary": "<brief summary>",
      "verification": {
        "scenarios": [ ... 逐场景结果（对齐 report.json 场景 schema）... ],
        "verdict": "verified" | "bug-found",
        "bugs": [ ... ]
      }
    }

本模块定义：
  - schema 常量（键名单点定义，避免与 agents/fast-track.md / 硬校验器三处漂移）
  - ``parse_fast_track_verification``：从 run 结果 dict 提取并规整验证段；
    缺失/非法返回 None（fail-closed，调用方按失败处理）

纯函数模块，无外部依赖；verdict_check 硬校验器与 pm_engine 派发分支共用。
"""

from typing import Optional
from pathlib import Path

# 验证段顶层键
VERIFICATION_KEY = "verification"
VERDICT_KEY = "verdict"
SCENARIOS_KEY = "scenarios"
BUGS_KEY = "bugs"

# 最终判定取值
VERDICT_VERIFIED = "verified"
VERDICT_BUG_FOUND = "bug-found"

# 逐场景状态取值
SCENARIO_STATUSES = ("pass", "fail", "error", "warning", "exempt")

# 非 PASS 状态（硬校验对这些场景校验证据与分类）
NON_PASS_STATUSES = ("fail", "error", "warning")


def _scenario_ok(sc: dict) -> bool:
    """逐场景结构最小完备：scenario_id/description/status 齐全且 status 合法。"""
    if not isinstance(sc, dict):
        return False
    sid = sc.get("scenario_id")
    desc = sc.get("description")
    status = sc.get("status")
    if not (isinstance(sid, str) and sid.strip()):
        return False
    if not (isinstance(desc, str) and desc.strip()):
        return False
    return status in SCENARIO_STATUSES


def parse_fast_track_verification(result: dict) -> Optional[dict]:
    """从 fast-track run 结果 dict 提取并规整验证段。

    Returns:
        规整后的验证段 dict：:

            {
              "scenarios": [...],
              "verdict": "verified" | "bug-found",
              "bugs": [...]
            }

        以下情况返回 None（fail-closed，调用方按失败重派处理）：
          - 入参非 dict
          - 无 ``verification`` 键或非 dict
          - 无 ``scenarios`` 或非 list / 为空
          - ``verdict`` 缺失或非合法取值
          - 场景条目结构不完整或 status 非法（任一条）
    """
    if not isinstance(result, dict):
        return None
    verification = result.get(VERIFICATION_KEY)
    if not isinstance(verification, dict):
        return None

    scenarios = verification.get(SCENARIOS_KEY)
    if not isinstance(scenarios, list) or not scenarios:
        return None
    if not all(_scenario_ok(sc) for sc in scenarios if isinstance(sc, dict)):
        return None

    verdict = verification.get(VERDICT_KEY)
    if verdict not in (VERDICT_VERIFIED, VERDICT_BUG_FOUND):
        return None

    bugs = verification.get(BUGS_KEY)
    if not isinstance(bugs, list):
        bugs = []

    return {
        SCENARIOS_KEY: scenarios,
        VERDICT_KEY: verdict,
        BUGS_KEY: bugs,
    }


def is_verified(verification: dict) -> bool:
    """验证段最终判定是否为通过（配合 parse 结果使用）。"""
    return verification is not None and verification.get(VERDICT_KEY) == VERDICT_VERIFIED


# ── fast-track 规模预估（add-fast-track-scale-precheck）─────────────────────
# 阈值常量（design D1 固化，注释样本依据）：
# - NORMAL_THRESHOLD: tasks.md 未勾选任务条数阈值（样本：fix-root-init-import-shadow 8+ 任务 vs fix-dispatch-wakeup-gap 1 任务）
# - HIGHER_THRESHOLD: tasks.md 未勾选任务条数阈值（大任务面）
# - SOURCE_FILE_WEIGHT: 源码文件数权重（.py/.ts/.tsx 文件）
# - TASK_WEIGHT: 任务条数权重
NORMAL_THRESHOLD = 3
HIGHER_THRESHOLD = 6
TASK_WEIGHT = 10
SOURCE_FILE_WEIGHT = 1


def estimate_spec_scale(spec_dir: Path) -> int:
    """按 tasks.md 未勾选任务条数 + spec 目录源码文件数加权返回规模分。

    tasks.md 缺失或读取失败记 WARNING 返回低档分（保守放行，design D2）。

    Args:
        spec_dir: spec 目录路径（如 spec/changes/<spec_name>）

    Returns:
        规模分（int），值越大任务越重。
    """
    import logging as _log
    import re as _re
    from pathlib import Path as _Path

    spec_path = _Path(spec_dir)
    if not spec_path.is_dir():
        return 0

    logger = _log.getLogger("fast_track_scale")

    # 1. 统计 tasks.md 未勾选任务条数
    tasks_path = spec_path / "tasks.md"
    unchecked_count = 0
    if tasks_path.is_file():
        try:
            text = tasks_path.read_text(encoding="utf-8")
            # 匹配 "- [ ]" 开头的任务行
            unchecked_count = len(_re.findall(r"^- \[ \] ", text, _re.MULTILINE))
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"fast-track 规模预估读取 {tasks_path} 失败（低档放行）: {e}")
            unchecked_count = 0
    else:
        logger.warning(f"fast-track 规模预估 tasks.md 缺失（低档放行）: {tasks_path}")

    # 2. 统计 spec 目录源码文件数（.py/.ts/.tsx）
    source_count = 0
    for ext in ("*.py", "*.ts", "*.tsx"):
        source_count += len(list(spec_path.rglob(ext)))

    # 3. 加权计算规模分
    scale = unchecked_count * TASK_WEIGHT + source_count * SOURCE_FILE_WEIGHT
    return scale


def budget_tier_for_scale(scale: int) -> str:
    """按 design D1 阈值返回档位（normal / higher / full）。

    阈值常量固化并注释样本依据（见模块级常量）。

    Args:
        scale: 规模分（estimate_spec_scale 的返回值）

    Returns:
        档位字符串："normal" / "higher" / "full"
    """
    if scale >= HIGHER_THRESHOLD * TASK_WEIGHT:
        return "full"
    elif scale >= NORMAL_THRESHOLD * TASK_WEIGHT:
        return "higher"
    else:
        return "normal"
