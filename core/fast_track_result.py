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


# ── fast-track 规模预估（add-fast-track-scale-precheck / 规模预检改版）──────
# 算分口径（2026-09-17 改版，取代旧「任务数×10 + spec 目录源码文件数」公式）：
# - TASK_WEIGHT:  每个未勾选任务 1 分
# - FILE_WEIGHT:  每个声明段交付物 2 分（kind ∈ modify/new/delete）
#
# 旧公式两处结构性缺陷（实测取证，见 .fenix/todo.md 与本 SPEC 记录）：
#   ① 「spec 目录内源码文件数」项在全库 53 个 spec 目录恒为 0——spec 目录只放
#      md/yaml，从不放源码，该项实际是死项，算式退化为「未勾任务数 × 10」；
#   ② 由此阈值被等价换算为固定任务数门槛（3/6 条），而派发时点「未勾选数」
#      等于「任务总数」（任务尚未开工），任何 ≥6 条任务的 spec 一律判 full。
#      实测预检 4 次触发 4 次全 full，normal/higher 两档结构上不可达。
#
# 新公式的「交付物」取自 tasks.md `## Deliverables` 声明段（planner 交付契约，
# 与交付物守卫同源解析），反映真实的改动面而非 spec 目录里的 md 文件数。
TASK_WEIGHT = 1
FILE_WEIGHT = 2

# 默认阈值（严格大于语义，见 budget_tier_for_scale）：
#   分值 ≤ higher_threshold            → normal
#   higher_threshold < 分值 ≤ full_threshold → higher
#   分值 > full_threshold              → full（fast-track 降级完整模式）
# 两阈值可经 agents.scale_precheck 配置覆盖（设置界面「预算」页签）。
DEFAULT_HIGHER_THRESHOLD = 30
DEFAULT_FULL_THRESHOLD = 45

# 配置键（agents.scale_precheck.*）与合法范围：阈值正整数且 higher < full。
SCALE_PRECHECK_CONFIG_KEY = "scale_precheck"
SCALE_PRECHECK_ENABLED_KEY = "enabled"
SCALE_PRECHECK_HIGHER_KEY = "higher_threshold"
SCALE_PRECHECK_FULL_KEY = "full_threshold"
SCALE_PRECHECK_ENABLED_DEFAULT = True
SCALE_PRECHECK_THRESHOLD_MIN = 1
SCALE_PRECHECK_THRESHOLD_MAX = 10000


def estimate_spec_scale(spec_dir: Path) -> int:
    """按 tasks.md 未勾选任务条数 + 声明段交付物数加权返回规模分。

    算分：``未勾选任务数 × TASK_WEIGHT + 声明段交付物数 × FILE_WEIGHT``。

    「声明段交付物」= tasks.md ``## Deliverables`` 段内 ``kind ∈ {modify, new,
    delete}`` 的条目（``reference`` 不计——它是语境引用，不是交付物；语义对齐
    ``core.deliverables._DECLARED_KINDS``）。解析复用 ``extract_declared``，
    与交付物守卫同源；无声明段时回退 ``extract_paths_typed`` 的 deliverables。

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

    # 2. 统计声明段交付物数（modify/new/delete；reference 不计）
    file_count = 0
    try:
        from core.deliverables import extract_declared, extract_paths_typed

        declared = extract_declared(spec_path)
        if declared is None:
            # 无声明段（存量 spec）：回退语境推断的 deliverables 口径
            declared = extract_paths_typed(spec_path)
        file_count = len((declared or {}).get("deliverables") or [])
    except Exception as e:
        # 解析失败保守低档放行（与 tasks.md 缺失同语义，不阻断派发）
        logger.warning(f"fast-track 规模预估解析交付物失败（低档放行）: {e}")
        file_count = 0

    # 3. 加权计算规模分
    return unchecked_count * TASK_WEIGHT + file_count * FILE_WEIGHT


def budget_tier_for_scale(
    scale: int,
    *,
    higher_threshold: int = DEFAULT_HIGHER_THRESHOLD,
    full_threshold: int = DEFAULT_FULL_THRESHOLD,
) -> str:
    """按阈值返回档位（normal / higher / full）。**严格大于**语义。

    - 分值 ≤ higher_threshold            → "normal"
    - higher_threshold < 分值 ≤ full_threshold → "higher"
    - 分值 > full_threshold              → "full"

    即阈值本身落在较低档（30 分仍 normal、45 分仍 higher），与配置界面
    注解一致。阈值经 ``agents.scale_precheck`` 覆盖，缺省 30 / 45。

    Args:
        scale: 规模分（estimate_spec_scale 的返回值）
        higher_threshold: higher 档下界（超过它才升档）
        full_threshold: full 档下界（超过它才降级完整模式）

    Returns:
        档位字符串："normal" / "higher" / "full"
    """
    if scale > full_threshold:
        return "full"
    if scale > higher_threshold:
        return "higher"
    return "normal"


def get_scale_precheck_config(config: dict) -> dict:
    """归一化 ``agents.scale_precheck`` 配置（供读侧与设置界面共用，单点缺省）。

    非法值逐项回退缺省并保证 ``higher_threshold < full_threshold``（两者
    相等或倒挂时整段回退缺省）——避免「展示值与生效值脱节」。

    Returns:
        ``{"enabled": bool, "higher_threshold": int, "full_threshold": int}``
    """
    agents = config.get("agents") if isinstance(config, dict) else None
    agents = agents if isinstance(agents, dict) else {}
    section = agents.get(SCALE_PRECHECK_CONFIG_KEY)
    section = section if isinstance(section, dict) else {}

    enabled = section.get(SCALE_PRECHECK_ENABLED_KEY, SCALE_PRECHECK_ENABLED_DEFAULT)
    if not isinstance(enabled, bool):
        enabled = SCALE_PRECHECK_ENABLED_DEFAULT

    def _threshold(key: str, default: int) -> int:
        val = section.get(key, default)
        if isinstance(val, bool) or not isinstance(val, int):
            return default
        if val < SCALE_PRECHECK_THRESHOLD_MIN or val > SCALE_PRECHECK_THRESHOLD_MAX:
            return default
        return val

    higher = _threshold(SCALE_PRECHECK_HIGHER_KEY, DEFAULT_HIGHER_THRESHOLD)
    full = _threshold(SCALE_PRECHECK_FULL_KEY, DEFAULT_FULL_THRESHOLD)
    if higher >= full:
        # 倒挂/相等：整段回退缺省（而非静默取其一），使 UI 与生效值一致
        higher, full = DEFAULT_HIGHER_THRESHOLD, DEFAULT_FULL_THRESHOLD

    return {
        "enabled": enabled,
        "higher_threshold": higher,
        "full_threshold": full,
    }
