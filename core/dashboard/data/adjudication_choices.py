"""core.dashboard.data.adjudication_choices — 裁决选项静态注册表（add-human-adjudication-choices D1）。

裁决本质是选择题（08-29~09-22 真实人工裁决复盘：全部裁决均为「在既有选项里
挑一个」）。本模块按 ``signal_type`` 静态映射桶 2（真需人决策）信号的裁决选项集：

- 发射点写告警时经 :func:`choices_for` 快照 ``choices`` 进告警记录（D2：告警是
  历史事实，注册表演进不回写历史告警的选项集）；
- 前端告警区对带 choices 的记录渲染下拉框 + 执行按钮；
- ``POST /api/alert-resolve`` 与 Administrator 处置消费按 ``action`` 字段映射到
  后端动词（admin_actions 既有动词 + 三个新裁决动词），三处共用同一事实源，
  MUST NOT 分散内联（D1）。

桶 0（知情/自愈类：stale_code、transient_break_storm、run_infra_failure 自动
恢复、run_cancelled、误报类）不在注册表内——:func:`choices_for` 对其返回空
元组，告警不携带 choices，前端只出「知道了」。

注册表为纯静态声明（模块常量），MUST NOT 依赖 LLM 生成。返回值为模块级共享
元组/字典，消费方 MUST NOT 就地改写（只读契约）。
"""

from __future__ import annotations

# 桶 2 真裁决类信号的裁决选项集（proposal 信号表全量 8 类）。
# 每个选项四字段：
#   id     稳定字符串（同信号内唯一）
#   label  中文短标签（下拉框显示）
#   desc   一句话说明执行内容（下拉选项次行 / 二次确认文案）
#   action 映射的后端动词标识（admin_actions 既有动词或新增裁决动词；
#          alert-resolve 端点按它分派 execute_adjudication_choice）
ADJUDICATION_CHOICES: dict = {
    # ── 验证循环耗尽族 ────────────────────────────────────────────
    "impl_budget_exhausted": (
        {
            "id": "continue_auto_fix",
            "label": "继续自动修复",
            "desc": "解冻并重置实现预算计数（重新获得完整实现预算），继续自动修复",
            "action": "continue_auto_fix",
        },
        {
            "id": "manual_fixed_reverify",
            "label": "人工已修复·重置验证重跑",
            "desc": "人工已修复问题：清场景与验证计数器后重置验证重跑",
            "action": "reset_verification",
        },
        {
            "id": "force_advance",
            "label": "接受现状推进",
            "desc": "人工豁免剩余缺口，spec 推进到 done 并解除冻结（留豁免痕）",
            "action": "force_advance",
        },
        {
            "id": "abandon",
            "label": "撤销丢弃",
            "desc": "撤销并丢弃该 spec 的工作（软删除归档，留处置痕，不可自动恢复）",
            "action": "abandon",
        },
    ),
    "judge_rerun_cap": (
        {
            "id": "manual_fixed_reverify",
            "label": "人工已修复·重置验证重跑",
            "desc": "人工已修复验证链问题：清场景文件与 judge/验证计数器后重置重验",
            "action": "reset_verification",
        },
        {
            "id": "force_advance",
            "label": "接受现状推进",
            "desc": "人工豁免剩余缺口，spec 推进到 done 并解除冻结（留豁免痕）",
            "action": "force_advance",
        },
        {
            "id": "abandon",
            "label": "撤销丢弃",
            "desc": "撤销并丢弃该 spec 的工作（软删除归档，留处置痕，不可自动恢复）",
            "action": "abandon",
        },
    ),
    "verify_fail_escalation": (
        {
            "id": "continue_auto_fix",
            "label": "继续自动修复",
            "desc": "解冻并重置验证失败轮计数（重新获得自动修复预算），继续自动修复",
            "action": "continue_auto_fix",
        },
        {
            "id": "manual_fixed_reverify",
            "label": "人工已修复·重置验证重跑",
            "desc": "人工已修复问题：清场景与验证失败轮计数后重置验证重跑",
            "action": "reset_verification",
        },
        {
            "id": "force_advance",
            "label": "接受现状推进",
            "desc": "人工豁免剩余缺口，spec 推进到 done 并解除冻结（留豁免痕）",
            "action": "force_advance",
        },
        {
            "id": "abandon",
            "label": "撤销丢弃",
            "desc": "撤销并丢弃该 spec 的工作（软删除归档，留处置痕，不可自动恢复）",
            "action": "abandon",
        },
    ),
    "redispatch_loop_detected": (
        {
            "id": "continue_auto_fix",
            "label": "继续自动修复",
            "desc": "解冻并清同因重派计数（同因重试从零起算），继续自动修复",
            "action": "continue_auto_fix",
        },
        {
            "id": "manual_fixed_reverify",
            "label": "人工已修复·重置验证重跑",
            "desc": "人工已修复问题：清场景与验证计数器后重置验证重跑",
            "action": "reset_verification",
        },
        {
            "id": "force_advance",
            "label": "接受现状推进",
            "desc": "人工豁免剩余缺口，spec 推进到 done 并解除冻结（留豁免痕）",
            "action": "force_advance",
        },
        {
            "id": "abandon",
            "label": "撤销丢弃",
            "desc": "撤销并丢弃该 spec 的工作（软删除归档，留处置痕，不可自动恢复）",
            "action": "abandon",
        },
    ),
    # ── 评审族 ───────────────────────────────────────────────────
    "spec-review-rejected": (
        {
            "id": "revise_reproposal",
            "label": "已修订方案·重新评审",
            "desc": "人工已按否决意见修订方案（proposal.md/design.md）：清否决计数、"
            "解冻回 reviewing 重新评审",
            "action": "revise_reproposal",
        },
        {
            "id": "force_advance",
            "label": "接受现状推进",
            "desc": "人工裁定方向仍成立，豁免评审门推进到 done（留豁免痕）",
            "action": "force_advance",
        },
        {
            "id": "abandon",
            "label": "撤销丢弃",
            "desc": "撤销并丢弃该 spec 的工作（软删除归档，留处置痕，不可自动恢复）",
            "action": "abandon",
        },
    ),
    "spec-review-incomplete": (
        {
            "id": "retry_review",
            "label": "重派评审",
            "desc": "评审链路已排查修复：解冻回 reviewing 重新派发评审",
            "action": "retry_review",
        },
        {
            "id": "skip_review_gate",
            "label": "人工授权跳过评审门",
            "desc": "评审器持续基础设施失败时人工授权放行：reviewing 直推 ready 进入"
            "正常实现调度（留授权痕）",
            "action": "skip_review_gate",
        },
        {
            "id": "abandon",
            "label": "撤销丢弃",
            "desc": "撤销并丢弃该 spec 的工作（软删除归档，留处置痕，不可自动恢复）",
            "action": "abandon",
        },
    ),
    # ── token 预算 ───────────────────────────────────────────────
    "token_budget": (
        {
            "id": "ignore",
            "label": "知情确认",
            "desc": "确认 token 消耗符合预期，仅关闭本条告警，不改动 spec 状态",
            "action": "ignore",
        },
        {
            "id": "freeze_stop_loss",
            "label": "冻结止损",
            "desc": "立即冻结该 spec（blocked + 冻结标记），停止自动派发止损",
            "action": "freeze_stop_loss",
        },
        {
            "id": "raise_budget",
            "label": "调大预算",
            "desc": "将 agents.token_budget_millions 翻倍并复位告警幂等标记，"
            "继续当前工作",
            "action": "raise_budget",
        },
    ),
    # ── 配置裁决类（kind=SIGNAL，经 Administrator 处置契约消费，不经前端告警区）──
    "build_artifact_paths_missing": (
        {
            "id": "open_config",
            "label": "去配置表单裁决",
            "desc": "引导到 Dashboard 配置表单填写 worktree.has_build_artifacts / "
            "build_artifact_paths（本动作仅确认信号，不代填配置）",
            "action": "open_config",
        },
        {
            "id": "declare_no_artifacts",
            "label": "声明无产物",
            "desc": "探测确认项目无构建产物：写 has_build_artifacts=false 结案"
            "（留处置痕）",
            "action": "declare_no_artifacts",
        },
    ),
}

# 消费通道约定（registry spec.md）：除 build_artifact_paths_missing 外，各信号的
# 告警记录均为 kind=ESCALATION（进前端告警区渲染下拉）；build_artifact_paths_missing
# 写 kind=SIGNAL 记录，不进前端告警区，其 choices 由 Administrator 处置契约消费。
SIGNAL_CHANNEL_SIGNAL_TYPES = ("build_artifact_paths_missing",)


def choices_for(signal_type) -> tuple:
    """按 signal_type 查询裁决选项集。

    未注册信号（含桶 0 知情/自愈类与 None/空值）返回空元组，不抛异常——
    发射点以「非空才写入 choices 字段」判定，桶 0 天然不携带。
    """
    return ADJUDICATION_CHOICES.get(str(signal_type or ""), ())


def is_adjudicable(signal_type) -> bool:
    """该 signal_type 是否在注册表内（桶 2 真裁决类判别）。"""
    return str(signal_type or "") in ADJUDICATION_CHOICES


def registered_signal_types() -> tuple:
    """注册表覆盖的全部 signal_type（发射点接线测试清单）。"""
    return tuple(ADJUDICATION_CHOICES.keys())
