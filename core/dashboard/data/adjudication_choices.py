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

注册表为纯静态声明（模块常量），MUST NOT 依赖 LLM 生成。只读契约由结构保证
（code-review item fb6a53a88d08）：注册表外层与各选项 dict 均冻结为
MappingProxyType，:func:`choices_for` 返回选项的逐项拷贝——消费方就地改写
要么直接 TypeError、要么只作用于拷贝，不再有跨告警污染注册表的通道。
"""

from __future__ import annotations

from types import MappingProxyType

# 桶 2 真裁决类信号的裁决选项集（初始覆盖 proposal 信号表 8 类，随演进按需
# 追加桶——勿引用本注释的计数作断言，覆盖清单以 registered_signal_types()
# 与测试 _EXPECTED_CHOICE_IDS 为准）。
# 每个选项四字段：
#   id     稳定字符串（同信号内唯一）
#   label  中文短标签（下拉框显示）
#   desc   一句话说明执行内容（下拉选项次行 / 二次确认文案）
#   action 映射的后端动词标识（admin_actions 既有动词或新增裁决动词；
#          alert-resolve 端点按它分派 execute_adjudication_choice）
# 可选第五字段：
#   destructive  True=不可逆/越权语义（abandon/skip_review_gate）；前端据此
#                决定执行前二次确认——确认门由注册表单源驱动，前端不再
#                硬编码业务 id（code-review item 19f72b875e8f；历史告警
#                快照缺该字段时前端按已知不可逆 id 回退）
# 可选第六字段：
#   spec_scoped  True=spec 作用域动作（动作语义针对某个具体 spec 的状态机，
#                如 retry_review/force_advance/abandon）；False=非作用域
#                （仅确认/观察/写项目配置，不触碰任何 spec 状态机）。缺省按
#                True 保守处理（fix-global-signal-choice-execution 1.1）：
#                执行器与消费端据此守卫——全局信号（spec 为空或占位 'global'）
#                MUST NOT 执行 spec 作用域动作（无 spec 可操作），非作用域
#                动作不受限且保留全表反查可达。
# 跨信号逐字共享的选项提为模块级单源（code-review item 7542b25da792），
# 各信号元组按引用复用：字段演进只改一处，不再多点同步。desc 带信号特定
# 文案的同名选项（judge/verify 链的 manual_fixed_reverify、评审族的
# force_advance）语义有差异，保持就地声明不强行合并。
_ABANDON = {
    "id": "abandon",
    "label": "撤销丢弃",
    "desc": "撤销并丢弃该 spec 的工作（软删除归档，留处置痕，不可自动恢复）",
    "action": "abandon",
    "destructive": True,
    "spec_scoped": True,
}
_FORCE_ADVANCE = {
    "id": "force_advance",
    "label": "接受现状推进",
    "desc": "人工豁免剩余缺口，spec 推进到 done 并解除冻结（留豁免痕）",
    "action": "force_advance",
    "spec_scoped": True,
}
_MANUAL_FIXED_REVERIFY = {
    "id": "manual_fixed_reverify",
    "label": "人工已修复·重置验证重跑",
    "desc": "人工已修复问题：清场景与验证计数器后重置验证重跑",
    "action": "reset_verification",
    "spec_scoped": True,
}

# fix-global-signal-choice-execution 1.3：全局形态信号的非作用域收口动作。
# 全局信号（spec 为空或占位 'global'，如 daemon_errors——注册表无此桶）被
# 执行守卫拒入 spec 作用域动作后，仍须有非作用域动作可收口，不滞留 pending
# 无路可走（design 决策 5）。声明在可能全局形态的已注册桶内
# （build_artifact_paths_missing 的 spec 允许为空串）保证注册表单源可见；
# 未注册 signal_type 经 resolve_choice 的「非 spec_scoped 动作全表反查放行」
# 可达。提示词呈现侧不过滤（design 决策 5，执行时守卫已兜底）。
_ACK_SELF_HEAL = {
    "id": "ack_self_heal",
    "label": "确认自愈·继续观察",
    "desc": "确认信号属瞬时/自愈或暂不需处置：仅留痕并关闭本条信号，"
            "不触碰任何 spec 状态机（全局信号可执行）",
    "action": "ack_self_heal",
    "spec_scoped": False,
}

# evo-add-commit-stray-wip-choice 1.1：主树散件 WIP 的提交动作（全局信号，
# spec 恒 None）。语义按处置记录 4c8be9a8ea40 / 4a1464085660 两次回填的
# suggested_choice 原文：核对归属后直接提交信号清单内散件改动、与 stash 类
# 动作互斥（提交后清单内文件不再滞留，stash 语义已被取代）、处置记录附提交
# hash。spec_scoped=False 硬约束（design D1）：maintree_stray_wip_stale 是
# 全局信号，全局信号守卫会拒 spec_scoped 选项——漏声明则选项永远执行不了。
# 执行端另受 signal_type 绑定守卫收口（admin_actions._exec_commit_stray_wip，
# design D4：resolve_choice 非作用域全表反查通道会把本动作暴露给任意未注册
# 信号，执行器 MUST 校验 signal_type 后才落 git 写）。
_COMMIT_STRAY_WIP = {
    "id": "commit_stray_wip",
    "label": "提交散件 WIP",
    "desc": "核对归属后直接提交主树信号清单内的散件改动（与 stash 类动作"
            "互斥，处置记录附提交 hash；全局信号可执行）",
    "action": "commit_stray_wip",
    "spec_scoped": False,
}

# evo-recurring-stray-remediation 1.1：主树散件的当场根治动作。被 track 的
# 生成物类散件（build 日志等）每次构建必然重新出现，「仅提交」只是把确定性
# 复发挂起（potplayer-base build-win-configure.log 三天两度处置实证）；
# untrack 断根：git rm --cached 出库 + .gitignore 追加（去重）+ 独立提交，
# 此后该路径改动由 ignore 规则自然吸收、不再产生散件告警。与 _COMMIT_STRAY_WIP
# 并存不互斥（提交留基线、untrack 断根，由处置者按复发形态选择）。
# spec_scoped=False + 执行端 signal_type 绑定守卫双保险，沿 _COMMIT_STRAY_WIP
# 同款先例（design D4：resolve_choice 非作用域全表反查通道对本动作同样可达，
# git 写暴露面由执行器收口到 maintree_stray_wip_stale）。
_UNTRACK_STRAY_WIP = {
    "id": "untrack_stray_wip",
    "label": "根治·散件出库",
    "desc": "复发型散件当场断根：对信号清单内文件执行 git rm --cached 出库、"
            ".gitignore 追加条目（已存在则不重复写）并以独立提交落地"
            "（结果附 untrack 清单与提交 hash；全局信号可执行）",
    "action": "untrack_stray_wip",
    "spec_scoped": False,
}

# evo-stray-untracked-escalation 3.2：untracked 散件认领三裁决（全局信号，
# spec 恒 None）。tracked 桶的 commit/untrack 不可复用：git rm --cached 对
# untracked 路径无语义、git add/commit 会把散件转正式 tracked 内容——认领
# 语义是「显式归档 / 补 ignore / 删除」三选一。spec_scoped=False 硬约束同款
# （全局信号守卫拒 spec_scoped 选项）；执行端 signal_type 绑定白名单双保险
# （admin_actions.UNTRACKED_CLAIM_SIGNAL_TYPES 仅收录 maintree_untracked_stray_
# escalated，姊妹 info 信号与 tracked 桶信号拒绝、零 git 写零文件触碰，
# design D4：resolve_choice 非作用域全表反查通道对本组动作同样可达）。
_ARCHIVE_UNTRACKED_STRAY = {
    "id": "archive_untracked_stray",
    "label": "认领·归档散件",
    "desc": "显式归档：把信号清单内 untracked 散件移入登记目录 "
            ".fenix/stray-archive/<时间戳>/（保留相对路径，登记目录追加 "
            "ignore 规则并以独立提交落地，不再触发盘点告警）",
    "action": "archive_untracked_stray",
    "spec_scoped": False,
}
_IGNORE_UNTRACKED_STRAY = {
    "id": "ignore_untracked_stray",
    "label": "认领·追加 ignore",
    "desc": "把信号清单内 untracked 路径追加进 .gitignore（去重：条目已存在"
            "或既有规则已覆盖的不重复写，独立提交落地）",
    "action": "ignore_untracked_stray",
    "spec_scoped": False,
}
_DELETE_UNTRACKED_STRAY = {
    "id": "delete_untracked_stray",
    "label": "认领·删除散件",
    "desc": "删除信号清单内的 untracked 散件文件（不可逆，仅普通文件，"
            "执行前二次确认）",
    "action": "delete_untracked_stray",
    "destructive": True,
    "spec_scoped": False,
}

_ADJUDICATION_REGISTRY: dict = {
    # ── 验证循环耗尽族 ────────────────────────────────────────────
    "impl_budget_exhausted": (
        {
            "id": "continue_auto_fix",
            "label": "继续自动修复",
            "desc": "解冻并重置实现预算计数（重新获得完整实现预算），继续自动修复",
            "action": "continue_auto_fix",
            "spec_scoped": True,
        },
        _MANUAL_FIXED_REVERIFY,
        _FORCE_ADVANCE,
        _ABANDON,
    ),
    "judge_rerun_cap": (
        {
            "id": "manual_fixed_reverify",
            "label": "人工已修复·重置验证重跑",
            "desc": "人工已修复验证链问题：清场景文件与 judge/验证计数器后重置重验",
            "action": "reset_verification",
            "spec_scoped": True,
        },
        _FORCE_ADVANCE,
        _ABANDON,
    ),
    "verify_fail_escalation": (
        {
            "id": "continue_auto_fix",
            "label": "继续自动修复",
            "desc": "解冻并重置验证失败轮计数（重新获得自动修复预算），继续自动修复",
            "action": "continue_auto_fix",
            "spec_scoped": True,
        },
        {
            "id": "manual_fixed_reverify",
            "label": "人工已修复·重置验证重跑",
            "desc": "人工已修复问题：清场景与验证失败轮计数后重置验证重跑",
            "action": "reset_verification",
            "spec_scoped": True,
        },
        _FORCE_ADVANCE,
        _ABANDON,
    ),
    # ── env 豁免握手 inconclusive 停车族（fix-env-exemption-exit-reachability
    # 4.1）────────────────────────────────────────────────────────
    # judge 已裁决全部失败归 env、豁免握手拦截（无 admin 放行记录不落
    # verified）后的升级停车。三选一：授予豁免（落 DISPOSITION 放行记录 +
    # 重置重验，下轮 verified 合法生效带豁免回链）/ 修环境重置重验 / 放弃。
    # 消费通道为 ESCALATION（前端告警区下拉），不加入 SIGNAL_CHANNEL_SIGNAL_
    # TYPES——SIGNAL 通道（Administrator 自动核查）与人工 choices 双通道并存。
    "inconclusive_loop": (
        {
            "id": "grant_env_exemption",
            "label": "授予 env 豁免",
            "desc": "确认失败确属环境且不可修复：落 env 豁免放行记录并重置验证"
            "重跑（下轮 verified 合法生效，报告带豁免回链）",
            "action": "grant_env_exemption",
            "spec_scoped": True,
        },
        {
            # evo-fix-env-exemption-gate-conflict-… 2.1：场景修订重验出口。
            # 失败确属场景定义不可行/夹具供给缺失（judge 或人工诊断结论）
            # 时，修订场景定义与夹具供给层文件并重置重验——先于升级的
            # re-entry 通道（修订后的重验轮再失败才升级停车）。修订次数有
            # 上限（SCENARIO_REVISION_MAX_COUNT，默认 2），超限拒绝并冻结
            # 转人工。载荷经 note 传 JSON：{"scenarios": [...], "reason":
            # "...", "fixture_files": [{"path", "content"}]}；文件路径仅限
            # 夹具供给层白名单（validate_scenario_revision_paths），产品
            # 代码路径拒绝。
            "id": "revise_scenario_reverify",
            "label": "修订场景·重验",
            "desc": "失败确属场景定义不可行/夹具缺供给：修订场景定义与夹具"
            "供给层文件（仅白名单路径）并重置重验（上限 2 次，超限转人工）",
            "action": "revise_scenario_reverify",
            "spec_scoped": True,
        },
        _MANUAL_FIXED_REVERIFY,
        _ABANDON,
    ),
    "redispatch_loop_detected": (
        {
            "id": "continue_auto_fix",
            "label": "继续自动修复",
            "desc": "解冻并清同因重派计数（同因重试从零起算），继续自动修复",
            "action": "continue_auto_fix",
            "spec_scoped": True,
        },
        _MANUAL_FIXED_REVERIFY,
        _FORCE_ADVANCE,
        _ABANDON,
    ),
    # ── 评审族 ───────────────────────────────────────────────────
    "spec-review-rejected": (
        {
            "id": "revise_reproposal",
            "label": "已修订方案·重新评审",
            "desc": "人工已按否决意见修订方案（proposal.md/design.md）：清否决计数、"
            "解冻回 reviewing 重新评审",
            "action": "revise_reproposal",
            "spec_scoped": True,
        },
        {
            "id": "force_advance",
            "label": "接受现状推进",
            "desc": "人工裁定方向仍成立，豁免评审门推进到 done（留豁免痕）",
            "action": "force_advance",
            "spec_scoped": True,
        },
        _ABANDON,
    ),
    "spec-review-incomplete": (
        {
            "id": "retry_review",
            "label": "重派评审",
            "desc": "评审链路已排查修复：解冻回 reviewing 重新派发评审",
            "action": "retry_review",
            "spec_scoped": True,
        },
        {
            "id": "skip_review_gate",
            "label": "人工授权跳过评审门",
            "desc": "评审器持续基础设施失败时人工授权放行：reviewing 直推 ready 进入"
            "正常实现调度（留授权痕）",
            "action": "skip_review_gate",
            "destructive": True,
            "spec_scoped": True,
        },
        _ABANDON,
    ),
    # ── token 预算 ───────────────────────────────────────────────
    "token_budget": (
        {
            "id": "ignore",
            "label": "知情确认",
            "desc": "确认 token 消耗符合预期，仅关闭本条告警，不改动 spec 状态",
            "action": "ignore",
            "spec_scoped": False,
        },
        {
            "id": "freeze_stop_loss",
            "label": "冻结止损",
            "desc": "立即冻结该 spec（blocked + 冻结标记），停止自动派发止损",
            "action": "freeze_stop_loss",
            "spec_scoped": True,
        },
        {
            "id": "raise_budget",
            "label": "调大预算",
            "desc": "将 agents.token_budget_millions 翻倍并复位告警幂等标记，"
            "继续当前工作",
            "action": "raise_budget",
            "spec_scoped": False,
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
            "spec_scoped": False,
        },
        {
            "id": "declare_no_artifacts",
            "label": "声明无产物",
            "desc": "探测确认项目无构建产物：写 has_build_artifacts=false 结案"
            "（留处置痕）",
            "action": "declare_no_artifacts",
            "spec_scoped": False,
        },
        _ACK_SELF_HEAL,
        # 本桶末位追加 _ACK_SELF_HEAL：该桶 spec 允许为空串（可能全局形态的
        # 已注册桶，见 _ACK_SELF_HEAL 处注释），非作用域收口动作声明于此，
        # 供未注册 signal_type 经全表反查到达（fix-global-signal-choice-execution 1.3）。
    ),
    # ── 主树散件 WIP 滞留族（evo-add-commit-stray-wip-choice 1.1）──────
    # 全局信号（spec 恒 None，core/worktree_manager/stray_wip.py 周期盘点发射）。
    # 消费通道为 ESCALATION 语义的告警区下拉（STORED_SIGNAL_TYPES 已收录，
    # Administrator 自动唤起与 Dashboard 人工点击双通道并存）。10-02 以来
    # 四度同型裁决全部 choice_id=None 自由处置，登记一次即塌缩复发裁决代价。
    "maintree_stray_wip_stale": (
        _COMMIT_STRAY_WIP,
        _UNTRACK_STRAY_WIP,
    ),
    # ── 主树 untracked 散件滞留升级族（evo-stray-untracked-escalation 3.2）──
    # 全局信号（spec 恒 None，stray_wip 第二档升级发射）。姊妹 info 信号
    # maintree_untracked_stray_stale 维持无桶（只告警不处置）——本桶仅登记
    # 在升级信号上，三裁决由认领执行器消费（绑定白名单收口）。
    "maintree_untracked_stray_escalated": (
        _ARCHIVE_UNTRACKED_STRAY,
        _IGNORE_UNTRACKED_STRAY,
        _DELETE_UNTRACKED_STRAY,
    ),
}

# 只读契约结构化（code-review item fb6a53a88d08）：构造期先以普通 dict 组装
# （选项常量被多信号按引用复用，组装逻辑不受影响），再整体冻结——外层注册表
# 与各选项 dict 均为 MappingProxyType，就地改写直接 TypeError。
ADJUDICATION_CHOICES: MappingProxyType = MappingProxyType({
    sig: tuple(MappingProxyType(choice) for choice in choices)
    for sig, choices in _ADJUDICATION_REGISTRY.items()
})

# 消费通道约定（registry spec.md）：除 build_artifact_paths_missing 外，各信号的
# 告警记录均为 kind=ESCALATION（进前端告警区渲染下拉）；build_artifact_paths_missing
# 写 kind=SIGNAL 记录，不进前端告警区，其 choices 由 Administrator 处置契约消费。
SIGNAL_CHANNEL_SIGNAL_TYPES = ("build_artifact_paths_missing",)


def choices_for(signal_type) -> tuple:
    """按 signal_type 查询裁决选项集。

    未注册信号（含桶 0 知情/自愈类与 None/空值）返回空元组，不抛异常——
    发射点以「非空才写入 choices 字段」判定，桶 0 天然不携带。

    返回普通 dict 的逐项拷贝（选项字段全为标量，浅拷贝即完全隔离）：
    键访问/迭代/isinstance(dict)/JSON 序列化形态与原共享元组一致，消费方
    即便就地改写也只作用于拷贝，不污染注册表（code-review item fb6a53a88d08）。
    """
    return tuple(
        dict(choice) for choice in ADJUDICATION_CHOICES.get(str(signal_type or ""), ())
    )


def is_adjudicable(signal_type) -> bool:
    """该 signal_type 是否在注册表内（桶 2 真裁决类判别）。"""
    return str(signal_type or "") in ADJUDICATION_CHOICES


def registered_signal_types() -> tuple:
    """注册表覆盖的全部 signal_type（发射点接线测试清单）。"""
    return tuple(ADJUDICATION_CHOICES.keys())


# 全局形态信号判定（fix-global-signal-choice-execution 1.2）：spec 为 None/空
# 串，或被空 spec 占位符顶替——core/agent_runner/maintenance_runs.py 以
# 'global' 占位空 spec（run 名、pending 记录、AdminDisposition.spec 均由此），
# 使全局信号在执行端表现为存在 spec 名。
GLOBAL_SPEC_PLACEHOLDER = "global"


def is_global_spec(spec) -> bool:
    """spec 是否全局形态（空值或占位 'global'）——无具体 spec 可操作。"""
    s = str(spec or "").strip()
    return (not s) or s.lower() == GLOBAL_SPEC_PLACEHOLDER


# ── 场景修订出口文件路径白名单（evo-fix-env-exemption-gate-conflict-… 2.1）──
# 修订出口只允许写「场景定义文件 + 夹具供给层」，防借修订改产品代码把验证
# 出口变成后门。场景定义文件（test_scenarios.json / _scenarios_full.json）由
# 执行器按固定文件名成对落盘、不经路径参数；本白名单约束的是夹具供给层
# 文件的相对路径（载荷 fixture_files[].path），以被验项目 project_root 锚定。
# 白名单不是黑名单：新增供给层目录须显式扩表（review 可见）。
SCENARIO_REVISION_ALLOWED_DIRS = (
    ".fenix/fixtures",   # 项目夹具供给目录（verify.yaml prepare 层供给的夹具资源）
    "fixtures",          # 被验项目自身夹具目录
    "tests/fixtures",    # 测试夹具目录
    "test/fixtures",
)
# 白名单内可直接改写的单文件（夹具供给层配置，非产品代码）
SCENARIO_REVISION_ALLOWED_FILES = (
    ".fenix/verify.yaml",
)


def validate_scenario_revision_paths(project_root, paths) -> str:
    """修订出口文件路径白名单校验（2.1；返回空串=全部合法，非空=拒绝理由）。

    规则（project_root 锚定，fail-closed）：
      1. 空/非字符串路径拒绝；
      2. 绝对路径（os.path.isabs，含 ``~`` 展开与 Windows 盘符形态）拒绝
         ——不以 project_root 为锚的路径一概不收；
      3. normpath 折叠后仍含 ``..`` 前导段（越出 project_root 的穿越）拒绝；
      4. 落点不在白名单目录/文件内 → 产品代码路径，拒绝。

    仅做路径形态判定，不做磁盘存在性检查（夹具文件可以是新建）。符号链接
    语义由写端实际机制决定：唯一写端 ``_exec_revise_scenario_reverify`` 经
    ``scenario_gate.atomic_write_text`` 落盘（mkstemp 临时文件 + os.replace）
    ——落点**末段**为符号链接时 rename 整体替换链接本身、不跟随写入；但
    **中间目录**若为指向项目外的符号链接，写端 ``mkdir`` 与 ``mkstemp`` 均
    跟随、夹具内容可落到白名单之外（现状不设防）。白名单只承诺「字面路径
    不可越出供给层」，末段替换与中间目录跟随均属写端语义，非本校验兜底。
    """
    import os

    base = os.path.abspath(str(project_root or ""))
    for raw in paths or []:
        p = str(raw or "").strip()
        if not p:
            return "夹具文件路径为空"
        if p.startswith("~") or os.path.isabs(p) or ":" in p.split("/")[0]:
            return f"拒绝绝对路径（修订仅允许项目内相对路径）：{p}"
        norm = os.path.normpath(p)
        if norm == "." or norm.startswith(".."):
            return f"拒绝路径穿越（越出项目根）：{p}"
        # project_root 锚定复核：base 拼接归一后必须仍落在 base 内（双重
        # 保险——norm 已无前导 ``..``，此处防 project_root 形态异常）
        anchored = os.path.abspath(os.path.join(base, norm))
        if anchored != base and not anchored.startswith(base + os.sep):
            return f"拒绝路径穿越（越出项目根）：{p}"
        parts = [seg for seg in norm.split("/") if seg not in ("", ".")]
        if not parts:
            return f"路径为项目根本身：{p}"
        posix_rel = "/".join(parts)
        allowed = (
            SCENARIO_REVISION_ALLOWED_DIRS + SCENARIO_REVISION_ALLOWED_FILES
        )
        if not any(
            posix_rel == a or posix_rel.startswith(a + "/") for a in allowed
        ):
            return (
                "路径不在夹具供给层白名单内（产品代码路径拒绝；仅允许 "
                f"{', '.join(allowed)}）：{p}"
            )
    return ""


def resolve_choice(choice_id, signal_type=""):
    """choice_id → (选项 dict 拷贝 | None, 拒绝原因)（注册表单源解析）。

    解析序与 ``execute_adjudication_choice`` 契约一致；执行器
    （admin_actions）与消费端守卫（admin_monitor._apply_choice_execution）
    共用本函数，防止双处解析漂移（fix-global-signal-choice-execution 1.1）：

    1. signal_type 已注册：桶内精确匹配；未命中 → (None, "not-in-bucket")
       （alert-resolve 契约「按 alert 的 signal_type 校验 choice_id 合法」，
       不跨信号放行）；
    2. signal_type 缺失/未注册：全表反查——同一 id 在各信号下 action 语义
       一致，但 spec 作用域动作（spec_scoped 缺省 True 保守）不再兜底放行
       （1.1 收紧只针对 spec_scoped 动作）→ (None, "scoped-no-reverse")；
       命中非作用域动作 → (拷贝, "")；
    3. 全表无此 id → (None, "unknown-choice")。

    返回选项的逐项拷贝（同 :func:`choices_for` 契约），消费方就地改写只作用
    于拷贝，不污染注册表。
    """
    cid = str(choice_id or "").strip()
    sig = str(signal_type or "")
    for c in ADJUDICATION_CHOICES.get(sig, ()):
        if c.get("id") == cid:
            return dict(c), ""
    if sig in ADJUDICATION_CHOICES:
        return None, "not-in-bucket"
    for sig_choices in ADJUDICATION_CHOICES.values():
        for c in sig_choices:
            if c.get("id") == cid:
                if c.get("spec_scoped", True):
                    return None, "scoped-no-reverse"
                return dict(c), ""
    return None, "unknown-choice"
