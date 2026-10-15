"""fast_track_result.py — fast-track 统一结果文件解析 + 规模预检/预算配置归一化。

前半部分为 fast-track 统一结果文件解析（add-fast-track-mode / D4）；后半部分为
spec 规模预检与 turn 预算 / wrapup 宽限 / wallclock 预算的配置归一化（evo spec 追加）。

fast-track run 复用现有 ``.fenix-run-result.json`` 机制，在其中增加验证段：

    {
      "status": "success" | "partial" | "error",
      "spec": "<spec>",
      "mode": "fast-track",
      "summary": "<brief summary>",
      "verification": {
        "scenarios": [ ... 逐场景结果（对齐 report.json 场景 schema）... ],
        "verdict": "verified" | "bug-found",
        "bugs": [ ... ]
      }
    }

    status 白名单权威源见 agents/fast-track.md（success/error/partial 三值），
    其中 ``partial`` 为做不完时的未完成收工态。

本模块定义：
  - schema 常量（键名单点定义，避免与 agents/fast-track.md / 硬校验器三处漂移）
  - ``parse_fast_track_verification``：从 run 结果 dict 提取并规整验证段；
    缺失/非法返回 None（fail-closed，调用方按失败处理）
  - 规模预检与预算配置归一化：``estimate_spec_scale`` / ``budget_tier_for_scale`` /
    ``get_scale_precheck_config`` / ``get_turn_budget_sizing_config`` /
    ``get_wrapup_grace_config`` / ``suggested_turn_cap_for_scale`` /
    ``get_impl_wallclock_sizing_config`` / ``lifted_max_extensions_for_scale``

纯函数模块：导入期无 core 依赖；``estimate_spec_scale`` /
``_impl_wallclock_default`` 在调用期惰性导入 ``core.deliverables`` 与
``core.config``（避免模块环）。verdict_check 硬校验器与 pm_engine 派发分支共用。
"""

import logging
import re
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
          - ``bugs`` 存在但非 list（缺失/``null`` 沿用历史口径容错规整为
            空列表，不判失败——verified 无 bug 时写侧可省略该字段）
    """
    if not isinstance(result, dict):
        return None
    verification = result.get(VERIFICATION_KEY)
    if not isinstance(verification, dict):
        return None

    scenarios = verification.get(SCENARIOS_KEY)
    if not isinstance(scenarios, list) or not scenarios:
        return None
    # 非 dict 条目交由 _scenario_ok 的 isinstance 防御判 False（fail-closed，
    # 与 docstring「场景条目结构不完整（任一条）返回 None」语义一致）
    if not all(_scenario_ok(sc) for sc in scenarios):
        return None

    verdict = verification.get(VERDICT_KEY)
    if verdict not in (VERDICT_VERIFIED, VERDICT_BUG_FOUND):
        return None

    bugs = verification.get(BUGS_KEY)
    if bugs is None:
        # 字段缺失沿用历史口径容错规整为空列表（verified 无 bug 时写侧可
        # 省略该字段，不据此判失败；``null`` 同此口径）。
        bugs = []
    elif not isinstance(bugs, list):
        # bugs 存在但非 list（LLM 把明细写成字符串/dict 等畸形形态）与
        # scenarios/verdict 同口径 fail-closed 返回 None（调用方按失败重派/
        # 产物门原地补写）：否则 verdict=bug-found 照常过硬校验而 bug 明细
        # 被静默清空，修复车道拿不到 bug 描述与场景关联、在无上下文下盲修。
        return None

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


def estimate_spec_scale(spec_dir: Path, logger=None) -> int:
    """按 tasks.md 未勾选任务条数 + 声明段交付物数加权返回规模分。

    算分：``未勾选任务数 × TASK_WEIGHT + 声明段交付物数 × FILE_WEIGHT``。

    「声明段交付物」= tasks.md ``## Deliverables`` 段内 ``kind ∈ {modify, new,
    delete}`` 的条目（``reference`` 不计——它是语境引用，不是交付物；语义对齐
    ``core.deliverables._DECLARED_KINDS``）。解析复用 ``extract_declared``，
    与交付物守卫同源；无声明段时回退 ``extract_paths_typed`` 的 deliverables。

    spec 目录缺失、tasks.md 缺失或读取失败记 WARNING 返回低档分（保守
    放行，design D2）。

    Args:
        spec_dir: spec 目录路径（如 spec/changes/<spec_name>）
        logger: 可选 ``core.logger.Logger`` 实例（code-review item
            49af374b79b7）。传入时 WARNING 经实例通道落**本项目** fenixd.log
            （core/logger.py 明示约定：core 落盘日志统一走 Logger 实例——裸
            ``getLogger("fenixd.*")`` 子日志器自身无 handler，多项目同进程下
            按传播语义串写最后构造项目的日志，输出项目归属不确定）；未传时
            （单测/独立调用）回退原裸 ``logging.getLogger`` 通道。

    Returns:
        规模分（int），值越大任务越重。
    """
    spec_path = Path(spec_dir)

    # 日志通道单点（code-review item 49af374b79b7）：调用方注入 Logger 实例
    # 则经实例通道落本项目日志；未注入回退裸 getLogger 通道（其项目归属
    # 不确定的局限见 core/logger.py 明示）。
    if logger is not None:

        def _warn(message: str) -> None:
            logger.warning("fast_track_scale", message)

    else:
        _bare_logger = logging.getLogger("fenixd.fast_track_scale")

        def _warn(message: str) -> None:
            _bare_logger.warning(message)

    if not spec_path.is_dir():
        _warn(f"fast-track 规模预估 spec 目录缺失（低档放行）: {spec_path}")
        return 0

    # 1. 统计 tasks.md 未勾选任务条数
    tasks_path = spec_path / "tasks.md"
    unchecked_count = 0
    if tasks_path.is_file():
        try:
            text = tasks_path.read_text(encoding="utf-8")
            # 匹配 "- [ ]" 开头的行。有意**不**要求任务编号（不与
            # run_task_track._TASK_CHECKBOX_RE / dashboard 任务行的
            # `^- \[(x| )\] \d+\.\d+` 编号口径对齐）：备注区、验证修复段等
            # 非编号杂散 checkbox 也计入规模分——只会轻度抬高、方向保守
            # （偏向 higher/full，预算只多不少）；而编号口径会漏计非标准
            # 编号形态的任务行（本模块单测夹具即用 `- [ ] 1.x` 形态），
            # 漏判方向是低估。取舍：宁可高估。
            unchecked_count = len(re.findall(r"^- \[ \] ", text, re.MULTILINE))
        except (OSError, UnicodeDecodeError) as e:
            _warn(f"fast-track 规模预估读取 {tasks_path} 失败（低档放行）: {e}")
            unchecked_count = 0
    else:
        _warn(f"fast-track 规模预估 tasks.md 缺失（低档放行）: {tasks_path}")

    # 2. 统计声明段交付物数（modify/new/delete；reference 不计）
    #    add-declaration-relocation-protocol D1：声明读取经统一解析入口
    #    resolve_effective_declaration，与收工守卫同源；当前调用只传
    #    project_root（派发时点 worktree 尚未创建、无现成实现分支上下文，
    #    未传 branch/worktree_path），分支/worktree 优先序不生效，实际
    #    仅主树口径；无声明段时回退语境推断的 deliverables 口径。
    #    project_root 由 spec_path 向上推导（spec_dir =
    #    project_root/spec/changes/<spec>）；推导出的 project_root 下
    #    不存在标准 spec 布局（测试/独立目录夹具）时回退直接解析
    #    spec_path（extract_declared 保有 kind 语义，reference 不计）。
    file_count = 0
    try:
        from core.deliverables import (
            extract_declared,
            extract_paths_typed,
            resolve_effective_declaration,
        )

        # 从 spec_dir 反推 project_root（spec_dir = project_root/spec/changes/<name>）
        spec_name = spec_path.name
        # 向上三层：<root>/spec/changes/<name> -> <root>（item 8a36fc320187）
        proj_root = spec_path.parent.parent.parent
        declared = None
        if proj_root.is_dir() and (
            proj_root / "spec" / "changes" / spec_name / "tasks.md"
        ).is_file():
            # 标准布局才走统一入口（当前仅主树口径，见上方注释）；
            # 非标准布局（如单测直接给 spec 目录）走下方直解析回退。
            declared = resolve_effective_declaration(
                spec_name,
                project_root=str(proj_root),
            )
        # .get 访问（code-review item 4b2acae9e21a）：resolve_effective_declaration
        # 契约漂移致键缺失时直接下标会抛 KeyError、被下方 except 吞成 file_count=0
        # 静默低估规模分——与回退路径的 .get 口径对齐，缺键交由 KeyError 分支
        # 显式记「疑似契约漂移」。
        if declared is None or (
            not declared.get("deliverables") and not declared.get("references")
        ):
            # 无标准布局 / 无声明段：先 extract_declared（保有 kind 语义——
            # reference 不计分），再无声明段回退语境推断的 deliverables 口径
            declared = extract_declared(spec_path)
            if declared is None:
                declared = extract_paths_typed(spec_path)
        _deliverables = (declared or {}).get("deliverables")
        # 类型漂移防御（code-review item 3d2f5380eeb7）：deliverables 契约漂移为
        # str/dict 时 len 会静默返回字符数/键数、虚高规模分偏向 full 档降级——
        # 非 list 视同缺键，与下方 KeyError 分支同语义显式记「疑似上游契约
        # 漂移」并置 0，避免掩盖上游断裂。
        if _deliverables is not None and not isinstance(_deliverables, list):
            _warn(
                "fast-track 规模预估交付物声明结构类型漂移"
                f"（deliverables 应为 list，实际 {type(_deliverables).__name__}，"
                "疑似上游契约漂移，低档放行）"
            )
            _deliverables = None
        file_count = len(_deliverables or [])
    except KeyError as e:
        # 契约漂移类异常与 IO/解析失败区分记录（不同 message），便于发现上游断裂
        _warn(f"fast-track 规模预估交付物声明结构缺键（疑似上游契约漂移，低档放行）: {e}")
        file_count = 0
    except Exception as e:
        # 解析失败保守低档放行（与 tasks.md 缺失同语义，不阻断派发）
        _warn(f"fast-track 规模预估解析交付物失败（低档放行）: {e}")
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

    契约：``higher_threshold`` MUST 小于 ``full_threshold``；相等或倒挂时
    本函数入口回退缺省阈值（与 ``get_scale_precheck_config`` 同语义），
    不抛异常——否则分值同时满足 ``>full`` 与 ``>higher``，先判 full 直接
    返回会使 higher 档不可达。

    Args:
        scale: 规模分（estimate_spec_scale 的返回值）
        higher_threshold: higher 档下界（超过它才升档）
        full_threshold: full 档下界（超过它才降级完整模式）

    Returns:
        档位字符串："normal" / "higher" / "full"
    """
    if higher_threshold >= full_threshold:
        # 阈值相等/倒挂：回退缺省阈值保档位语义（不抛异常，兼容现有调用面）
        higher_threshold = DEFAULT_HIGHER_THRESHOLD
        full_threshold = DEFAULT_FULL_THRESHOLD
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


# ── impl run 轮数预算 sizing（evo-add-impl-run-budget-sizing 1.1）────────────
# 配置键（agents.turn_budget_sizing.*）与合法域：实现车道 run 启动时按
# estimate_spec_scale 规模分推算生效轮数上限（design D3/D7）。推算开关缺省
# 开（大 spec 抬高起点上限，消除 cimbar 形「烧满熔断→续做再耗数百轮」主
# 浪费段）；kill_early（末位扩容拆停守卫）缺省关——沿 run_stall_budget
# 缺省关闭灰度先例（evo-add-run-stop-loss），不动摇 ADR-103 续期矩阵不变量。
TURN_BUDGET_SIZING_CONFIG_KEY = "turn_budget_sizing"
TURN_BUDGET_ENABLED_KEY = "enabled"
TURN_BUDGET_FULL_SCALE_THRESHOLD_KEY = "full_scale_threshold"
TURN_BUDGET_SUGGESTED_TURN_CAP_KEY = "suggested_turn_cap"
TURN_BUDGET_BOOKKEEPING_SHARE_KEY = "bookkeeping_share_threshold"
TURN_BUDGET_KILL_EARLY_KEY = "kill_early"
TURN_BUDGET_KILL_EARLY_ENABLED_KEY = "enabled"
TURN_BUDGET_KILL_EARLY_REMAINING_KEY = "remaining_tasks_threshold"
TURN_BUDGET_KILL_EARLY_PROGRESS_FLOOR_KEY = "progress_floor"

DEFAULT_TURN_BUDGET_ENABLED = True
# full 档阈值缺省 45：与 budget_tier_for_scale 的 DEFAULT_FULL_THRESHOLD 同源
# 取值（estimate_spec_scale 口径下 38 任务 + 40 交付物 ≈ 118 分的实证 spec
# 远超此阈），语义独立不共用常量——两处阈值后续可独立收敛。
DEFAULT_TURN_BUDGET_FULL_SCALE_THRESHOLD = 45
DEFAULT_TURN_BUDGET_SUGGESTED_TURN_CAP = 800
DEFAULT_TURN_BUDGET_BOOKKEEPING_SHARE_THRESHOLD = 0.5
DEFAULT_KILL_EARLY_ENABLED = False
DEFAULT_KILL_EARLY_REMAINING_TASKS_THRESHOLD = 10
DEFAULT_KILL_EARLY_PROGRESS_FLOOR = 0.1

# 正整数键的合法域（风格对齐 scale_precheck：非 bool 的 int，且在闭区间内）。
TURN_BUDGET_INT_MIN = 1
TURN_BUDGET_INT_MAX = 10000


def get_turn_budget_sizing_config(config: dict) -> dict:
    """归一化 ``agents.turn_budget_sizing`` 配置（读侧与设置界面共用，单点缺省）。

    非法值逐项回退缺省（风格对齐 ``get_scale_precheck_config``，不抛异常）：

    - ``enabled``: 布尔，缺省 True（推算抬升缺省开启）；
    - ``full_scale_threshold`` / ``suggested_turn_cap``: 正整数，缺省 45 / 800；
    - ``bookkeeping_share_threshold``: 数值 [0,1]，缺省 0.5（bool 不算数值）；
    - ``kill_early.enabled``: 布尔，缺省 False（末位扩容拆停守卫缺省关闭）；
    - ``kill_early.remaining_tasks_threshold``: 正整数，缺省 10；
    - ``kill_early.progress_floor``: 数值 [0,1]，缺省 0.1。

    Returns:
        ``{"enabled": bool, "full_scale_threshold": int, "suggested_turn_cap": int,
        "bookkeeping_share_threshold": float, "kill_early": {"enabled": bool,
        "remaining_tasks_threshold": int, "progress_floor": float}}``
    """
    agents = config.get("agents") if isinstance(config, dict) else None
    agents = agents if isinstance(agents, dict) else {}
    section = agents.get(TURN_BUDGET_SIZING_CONFIG_KEY)
    section = section if isinstance(section, dict) else {}

    def _int(sect: dict, key: str, default: int) -> int:
        val = sect.get(key, default)
        if isinstance(val, bool) or not isinstance(val, int):
            return default
        if val < TURN_BUDGET_INT_MIN or val > TURN_BUDGET_INT_MAX:
            return default
        return val

    def _ratio(sect: dict, key: str, default: float) -> float:
        val = sect.get(key, default)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return default
        if val < 0.0 or val > 1.0:
            return default
        return float(val)

    enabled = section.get(TURN_BUDGET_ENABLED_KEY, DEFAULT_TURN_BUDGET_ENABLED)
    if not isinstance(enabled, bool):
        enabled = DEFAULT_TURN_BUDGET_ENABLED

    kill_raw = section.get(TURN_BUDGET_KILL_EARLY_KEY)
    kill_raw = kill_raw if isinstance(kill_raw, dict) else {}
    kill_enabled = kill_raw.get(
        TURN_BUDGET_KILL_EARLY_ENABLED_KEY, DEFAULT_KILL_EARLY_ENABLED)
    if not isinstance(kill_enabled, bool):
        kill_enabled = DEFAULT_KILL_EARLY_ENABLED

    return {
        "enabled": enabled,
        "full_scale_threshold": _int(
            section, TURN_BUDGET_FULL_SCALE_THRESHOLD_KEY,
            DEFAULT_TURN_BUDGET_FULL_SCALE_THRESHOLD),
        "suggested_turn_cap": _int(
            section, TURN_BUDGET_SUGGESTED_TURN_CAP_KEY,
            DEFAULT_TURN_BUDGET_SUGGESTED_TURN_CAP),
        "bookkeeping_share_threshold": _ratio(
            section, TURN_BUDGET_BOOKKEEPING_SHARE_KEY,
            DEFAULT_TURN_BUDGET_BOOKKEEPING_SHARE_THRESHOLD),
        "kill_early": {
            "enabled": kill_enabled,
            "remaining_tasks_threshold": _int(
                kill_raw, TURN_BUDGET_KILL_EARLY_REMAINING_KEY,
                DEFAULT_KILL_EARLY_REMAINING_TASKS_THRESHOLD),
            "progress_floor": _ratio(
                kill_raw, TURN_BUDGET_KILL_EARLY_PROGRESS_FLOOR_KEY,
                DEFAULT_KILL_EARLY_PROGRESS_FLOOR),
        },
    }


# ── 收尾宽限配置（evo-add-admin-run-wrapup-contract 1.1/1.2）──────────────
# admin/维护等非实现车道在轮数/墙钟末次扩容点的一次性收尾宽限：轮数侧发
# turns 轮、墙钟侧按秒折算同一轮数（runner._wrapup_grace_grant 单点折算）。
# 两侧共用同一配置开关键（design 1.2）。缺省开启——该机制是事故修复本体
# （admin-pack2-official-encoder-1791196033 在最终处置记录落盘瞬间被 600 轮
# 上限击杀），且发放条件三重收紧（车道 ∈ 非实现集合、run 内自建任务全部
# completed、每 run 至多一次），误发放面与既有续期同级。
WRAPUP_GRACE_CONFIG_KEY = "wrapup_grace"
WRAPUP_GRACE_ENABLED_KEY = "enabled"
WRAPUP_GRACE_TURNS_KEY = "turns"
DEFAULT_WRAPUP_GRACE_ENABLED = True
DEFAULT_WRAPUP_GRACE_TURNS = 20


def get_wrapup_grace_config(config: dict) -> dict:
    """归一化 ``agents.wrapup_grace`` 配置（读侧单点缺省，风格对齐
    ``get_turn_budget_sizing_config``，非法值逐项回退缺省、不抛异常）：

    - ``enabled``: 布尔，缺省 True（收尾宽限总开关，轮数/墙钟两侧共用）；
    - ``turns``: 非负整数，缺省 20（宽限轮数；0 等价关闭）。

    Returns:
        ``{"enabled": bool, "turns": int}``
    """
    agents = config.get("agents") if isinstance(config, dict) else None
    agents = agents if isinstance(agents, dict) else {}
    section = agents.get(WRAPUP_GRACE_CONFIG_KEY)
    section = section if isinstance(section, dict) else {}

    enabled = section.get(WRAPUP_GRACE_ENABLED_KEY, DEFAULT_WRAPUP_GRACE_ENABLED)
    if not isinstance(enabled, bool):
        enabled = DEFAULT_WRAPUP_GRACE_ENABLED

    turns = section.get(WRAPUP_GRACE_TURNS_KEY, DEFAULT_WRAPUP_GRACE_TURNS)
    if isinstance(turns, bool) or not isinstance(turns, int) \
            or not (0 <= turns <= TURN_BUDGET_INT_MAX):
        turns = DEFAULT_WRAPUP_GRACE_TURNS

    return {"enabled": enabled, "turns": int(turns)}


def suggested_turn_cap_for_scale(base_turn_cap: int, scale: int, cfg: dict) -> int:
    """按规模分推算生效轮数上限（evo-add-impl-run-budget-sizing design D3）。

    ``enabled`` 且 ``scale`` **严格大于** ``full_scale_threshold`` 时返回
    ``max(base_turn_cap, suggested_turn_cap)``——推算只抬不压，永不低于
    base；否则原样返回 base（规模分等于阈值不抬，与 ``budget_tier_for_scale``
    的严格大于语义同源）。

    Args:
        base_turn_cap: 基础轮数上限（``agents.max_turns``）。
        scale: 规模分（``estimate_spec_scale`` 的返回值）。
        cfg: ``get_turn_budget_sizing_config`` 的返回值（契约：调用方先归一化）。

    Returns:
        生效轮数上限（int）。
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    if not cfg.get(TURN_BUDGET_ENABLED_KEY, DEFAULT_TURN_BUDGET_ENABLED):
        return base_turn_cap
    threshold = cfg.get(
        TURN_BUDGET_FULL_SCALE_THRESHOLD_KEY, DEFAULT_TURN_BUDGET_FULL_SCALE_THRESHOLD)
    suggested = cfg.get(
        TURN_BUDGET_SUGGESTED_TURN_CAP_KEY, DEFAULT_TURN_BUDGET_SUGGESTED_TURN_CAP)
    if (isinstance(scale, int) and not isinstance(scale, bool)
            and isinstance(threshold, int) and not isinstance(threshold, bool)
            and isinstance(suggested, int) and not isinstance(suggested, bool)
            and scale > threshold):
        return max(base_turn_cap, suggested)
    return base_turn_cap


# ── impl 车道墙钟预算 sizing（evo-add-impl-wallclock-budget-sizing 1.1）────
# 配置键（agents.impl_wallclock_sizing.*）：实现车道 deadline 监督按
# estimate_spec_scale 总规模分抬升续期预算 max_extensions（design 决策 1，
# 泛化 fast-track higher 档 +2 先例；fast-track 车道既有加成行为不动）。
# 只抬不压、缺省向后兼容、关闭/非法值回退缺省；STATE 覆盖键
# impl_wallclock_extension_override 在消费点（liveness）优先于本推算。
# 缺省值单源于 core.config.IMPL_WALLCLOCK_SIZING_DEFAULTS（SUPERVISION_
# DEFAULTS 旁，与监督缺省同处维护），本模块只做归一化与档位推算。
IMPL_WALLCLOCK_SIZING_CONFIG_KEY = "impl_wallclock_sizing"
IMPL_WALLCLOCK_ENABLED_KEY = "enabled"
IMPL_WALLCLOCK_FULL_SCALE_THRESHOLD_KEY = "full_scale_threshold"
IMPL_WALLCLOCK_EXTRA_EXTENSIONS_KEY = "extra_extensions"
# 正整数（extra 允许 0=显式不抬）键的合法域（风格对齐 TURN_BUDGET_INT_*）。
IMPL_WALLCLOCK_INT_MIN = 0
IMPL_WALLCLOCK_INT_MAX = 10000

# 硬编码字面缺省（code-review item cc6365304445）：与 core.config.
# IMPL_WALLCLOCK_SIZING_DEFAULTS 现值逐字段一致，仅在上游键漂移或常量
# 整体缺失/改名回退时使用（正常路径仍单源于 core.config，行为零变化）。
_IMPL_WALLCLOCK_FALLBACK_DEFAULTS = {
    "enabled": True,
    "full_scale_threshold": 45,
    "extra_extensions": 2,
}


def _impl_wallclock_default(key: str):
    """读墙钟 sizing 单点缺省（core.config；惰性导入避免模块环）。

    KeyError/ImportError 回退硬编码字面缺省：本模块
    get_impl_wallclock_sizing_config / lifted_max_extensions_for_scale 声明
    「非法值逐项回退缺省、不抛异常」，core.config 侧常量键漂移时不让
    KeyError 穿透读侧（与 estimate_spec_scale 的 KeyError 分支口径对齐，
    显式记「疑似上游契约漂移」）；常量整体缺失/改名时导入失败同样回退，
    不让 ImportError 沿配置归一化路径向上传播（code-review item
    dc3ffe79dbda）。
    """
    try:
        from core.config import IMPL_WALLCLOCK_SIZING_DEFAULTS
        return IMPL_WALLCLOCK_SIZING_DEFAULTS[key]
    except (ImportError, KeyError) as e:
        logging.getLogger("fenixd.fast_track_scale").warning(
            "fast-track 墙钟 sizing 缺省读取失败"
            f"（疑似上游契约漂移，回退硬编码字面缺省）: {e}")
        return _IMPL_WALLCLOCK_FALLBACK_DEFAULTS[key]


def get_impl_wallclock_sizing_config(config: dict) -> dict:
    """归一化 ``agents.impl_wallclock_sizing`` 配置（读侧与设置界面共用，单点缺省）。

    非法值逐项回退缺省（风格对齐 ``get_turn_budget_sizing_config``，不抛异常）：

    - ``enabled``: 布尔，缺省 True（推算抬升缺省开启）；
    - ``full_scale_threshold``: 非负整数，缺省 45（与轮数 sizing 缺省同值，
      语义独立不共用常量）；
    - ``extra_extensions``: 非负整数，缺省 2（0 = enabled 下显式不抬）。

    Returns:
        ``{"enabled": bool, "full_scale_threshold": int, "extra_extensions": int}``
    """
    agents = config.get("agents") if isinstance(config, dict) else None
    agents = agents if isinstance(agents, dict) else {}
    section = agents.get(IMPL_WALLCLOCK_SIZING_CONFIG_KEY)
    section = section if isinstance(section, dict) else {}

    def _int(sect: dict, key: str, default: int) -> int:
        val = sect.get(key, default)
        if isinstance(val, bool) or not isinstance(val, int):
            return default
        if val < IMPL_WALLCLOCK_INT_MIN or val > IMPL_WALLCLOCK_INT_MAX:
            return default
        return val

    enabled = section.get(IMPL_WALLCLOCK_ENABLED_KEY, _impl_wallclock_default("enabled"))
    if not isinstance(enabled, bool):
        enabled = _impl_wallclock_default("enabled")

    return {
        "enabled": enabled,
        "full_scale_threshold": _int(
            section, IMPL_WALLCLOCK_FULL_SCALE_THRESHOLD_KEY,
            _impl_wallclock_default("full_scale_threshold")),
        "extra_extensions": _int(
            section, IMPL_WALLCLOCK_EXTRA_EXTENSIONS_KEY,
            _impl_wallclock_default("extra_extensions")),
    }


def lifted_max_extensions_for_scale(
    base_max_extensions: int, scale: int, cfg: dict,
) -> int:
    """按规模分推算 impl 车道生效续期预算（只抬不压，1.1/1.2）。

    ``enabled`` 且 ``scale`` **严格大于** ``full_scale_threshold`` 时返回
    ``max(base_max_extensions, base_max_extensions + extra_extensions)``
    ——推算只抬不压，永不低于 base；否则原样返回 base（规模分等于阈值不抬，
    与 ``budget_tier_for_scale`` / ``suggested_turn_cap_for_scale`` 的严格
    大于语义同源）。

    幂等契约（design「档位幂等」）：``scale`` 取 run 启动同源总规模
    （``estimate_spec_scale`` 单点）且同 run 各次 deadline 判定复用同一入参
    ——禁止以 remaining_tasks 回算：剩余数随 tasks.md 推进递减，逐 deadline
    重算会回撤已抬档位，使 extensions_used ≥ 回撤后 max_extensions 触发伪
    "extension budget exhausted" 击杀。

    Args:
        base_max_extensions: 基础续期预算（``agents.timeout_supervision.
            max_extensions``，经 ``_supervision_settings`` 归一）。
        scale: 规模分（run 启动点 ``estimate_spec_scale`` 返回值）。
        cfg: ``get_impl_wallclock_sizing_config`` 的返回值（契约：调用方先归一化）。

    Returns:
        生效续期预算（int）。
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    if not cfg.get(IMPL_WALLCLOCK_ENABLED_KEY, _impl_wallclock_default("enabled")):
        return base_max_extensions
    threshold = cfg.get(
        IMPL_WALLCLOCK_FULL_SCALE_THRESHOLD_KEY,
        _impl_wallclock_default("full_scale_threshold"))
    extra = cfg.get(
        IMPL_WALLCLOCK_EXTRA_EXTENSIONS_KEY,
        _impl_wallclock_default("extra_extensions"))
    if (isinstance(scale, int) and not isinstance(scale, bool)
            and isinstance(threshold, int) and not isinstance(threshold, bool)
            and isinstance(extra, int) and not isinstance(extra, bool)
            and scale > threshold):
        return max(base_max_extensions, base_max_extensions + extra)
    return base_max_extensions
