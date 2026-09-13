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

from pathlib import Path
from pathlib import Path
from typing import Optional

# ── fast-track 派发前规模预估（evo-add-fast-track-scale-precheck D1）───────────
# tasks.md 未勾选任务条数 + spec 目录源码文件数作为轻量静态预估（零成本、
# 确定性、可单测）；对照样本验证可区分：
#   - fix-dispatch-wakeup-gap（单任务、小文件面）→ 低分 → normal
#   - fix-root-init-import-shadow（多任务、大文件面）→ 高分 → full
#
# 加权规则（模块级常量，非配置键——内部治理参数，参照 TURN_EXTENSION_MAX 先例）：
# - 每条未勾选任务（tasks.md `- [ ]` 行）：SCALE_TASK_WEIGHT 分
# - 每个源码文件（.py/.ts/.tsx，递归）：SCALE_FILE_WEIGHT 分

SCALE_TASK_WEIGHT = 10   # 每条未勾选任务的权重（任务数是首要规模信号）
SCALE_FILE_WEIGHT = 3    # 每个源码文件的权重（文件面是次级规模信号）

# 源码文件后缀（与 design D1 一致：.py/.ts/.tsx）
SOURCE_FILE_SUFFIXES = {".py", ".ts", ".tsx"}

# 分档阈值（模块级常量）
SCALE_TIER_NORMAL = "normal"
SCALE_TIER_HIGHER = "higher"
SCALE_TIER_FULL = "full"

SCALE_HIGHER_THRESHOLD = 30   # scale ≥ 30 → higher（约 3 条任务或 10 个文件）
SCALE_FULL_THRESHOLD = 80     # scale ≥ 80 → full（约 8 条任务或 26 个文件）


def estimate_spec_scale(spec_dir: Path, logger=None) -> int:
    """按 spec 的 tasks.md 未勾选任务条数 + spec 目录源码文件数加权返回规模分。

    ``tasks.md`` 缺失或读取失败时：记 WARNING（若 logger 非 None）并返回低档分（0）；
    不阻断调用方（与 design D2 预检失败保守放行一致）。

    Args:
        spec_dir: SPEC 目录路径（spec/changes/<spec_name>/）
        logger: 可选 Logger 实例；为 None 时 WARNING 降级为静默（纯函数可单测）

    Returns:
        规模分（int ≥ 0）。分数含义：
          0-29：small spec
          30-79：medium spec（higher tier）
          80+：large spec（full tier）
    """
    # ── tasks.md 未勾选任务条数 ──
    tasks_path = spec_dir / "tasks.md"
    if not tasks_path.is_file():
        # design D2：tasks.md 缺失 → 记 WARNING（若 logger）并返回低档分
        #（不因预检失败阻断合法派发）
        if logger is not None:
            logger.warning(
                "fast_track_result",
                f"estimate_spec_scale: tasks.md 缺失 '{spec_dir}'，"
                f"返回低档分（保守放行）",
            )
        return 0
    unchecked_tasks = 0
    try:
        content = tasks_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- [ ]") or stripped.startswith("- [x]"):
                if stripped.startswith("- [ ]"):
                    unchecked_tasks += 1
    except (OSError, UnicodeDecodeError) as e:
        # design D2：tasks.md 读取失败 → 记 WARNING 并返回低档分
        if logger is not None:
            logger.warning(
                "fast_track_result",
                f"estimate_spec_scale: tasks.md 读取失败 '{spec_dir}': {e}，"
                f"返回低档分（保守放行）",
            )
        return 0

    # ── spec 目录源码文件数（递归） ──
    source_files = 0
    try:
        for f in spec_dir.rglob("*"):
            if f.is_file() and f.suffix in SOURCE_FILE_SUFFIXES:
                source_files += 1
    except OSError:
        pass  # glob 异常 → 源码文件数 0（保守降级）

    scale = unchecked_tasks * SCALE_TASK_WEIGHT + source_files * SCALE_FILE_WEIGHT
    return max(0, scale)


def budget_tier_for_scale(scale: int) -> str:
    """按 design D1 阈值返回规模档位（normal / higher / full）。

    阈值固化在模块级常量（不进 config.yaml，参照 AGENT_TERMINATE_GRACE_SECONDS 先例）；
    分档含义：
      - normal：原有 fast-track 预算不变（extension_seconds=1800, max_extensions=2）
      - higher：延长 extension 预算（max_extensions +1，总预算 +extension_seconds）
      - full：降级为完整模式（implementer + verifier 分离流水线）
    """
    if scale >= SCALE_FULL_THRESHOLD:
        return SCALE_TIER_FULL
    if scale >= SCALE_HIGHER_THRESHOLD:
        return SCALE_TIER_HIGHER
    return SCALE_TIER_NORMAL

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
