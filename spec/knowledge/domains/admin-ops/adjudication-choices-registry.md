<!-- knowledge: capability=adjudication-choices-registry rev=5
     sources=spec/archive/2026-09-27-add-human-adjudication-choices,spec/archive/2026-10-09-evo-fix-global-signal-choice-execution,spec/archive/2026-10-08-fix-env-exemption-exit-reachability,spec/archive/2026-10-15-evo-fix-env-exemption-gate-conflict-and-scenario-revision-exit,spec/archive/2026-10-26-evo-add-commit-stray-wip-choice,spec/archive/2026-10-27-evo-recurring-stray-remediation -->

# 裁决选项静态注册表

按 signal_type 映射裁决选项集的纯静态注册表（`core/dashboard/data/adjudication_choices.py`），是人工下拉处置与 Administrator 自动处置共用的裁决空间。

## 现行规则

- 注册表为模块常量/常量函数的纯静态声明，不依赖 LLM 生成；每个选项含 `id`（稳定字符串，同信号内唯一）、`label`（中文短标签）、`desc`（一句话执行说明）、`action`（映射的后端动作标识，复用既有动词或裁决动词）。
- 桶 2（真裁决类）信号必须提供的选项集：

| signal_type | 选项（id 语义） |
|---|---|
| `impl_budget_exhausted` | continue_auto_fix（解冻+调大预算继续）/ manual_fixed_reverify（人工已修复，重置验证重跑）/ force_advance（接受现状收尾推进）/ abandon（撤销丢弃） |
| `judge_rerun_cap` | manual_fixed_reverify / force_advance / abandon |
| `verify_fail_escalation`（验证失败升级闸门） | continue_auto_fix（解冻+重置失败轮计数）/ manual_fixed_reverify / force_advance / abandon |
| `inconclusive_loop`（env 豁免握手 inconclusive 升级停车） | grant_env_exemption（确认失败属环境且不可修复：写 spec 级 STATE 豁免落放行+重置重验，下轮 verified 合法生效带豁免回链）/ revise_scenario_reverify（修订场景定义与夹具供给层文件·重验，白名单路径，上限 2 次超限冻结转人工）/ manual_fixed_reverify / abandon |
| `redispatch_loop_detected` | continue_auto_fix（解冻+清同因计数）/ manual_fixed_reverify / force_advance / abandon |
| `spec-review-rejected`（评审否决达上限） | revise_reproposal（按否决意见改方案重评）/ force_advance / abandon |
| `spec-review-incomplete`（评审器连坏） | retry_review（解冻重派评审）/ skip_review_gate / abandon |
| `token_budget` | ignore（知情确认）/ freeze_stop_loss（冻结止损）/ raise_budget（调大预算） |
| `build_artifact_paths_missing` | open_config（引导到配置表单）/ declare_no_artifacts（声明无产物）/ ack_self_heal（确认自愈·继续观察） |
| `maintree_stray_wip_stale`（主树散件 WIP 滞留升级，全局信号） | commit_stray_wip（提交散件 WIP：核对归属后直接提交主树信号清单内散件改动，与 stash 类动作互斥，处置记录附提交 hash）/ untrack_stray_wip（根治·散件出库：对信号清单内文件执行 git rm --cached 出库、.gitignore 追加条目（已存在则不重复写）并以独立提交落地，此后该路径改动由 ignore 规则自然吸收，结果附 untrack 清单与提交 hash） |

- 消费通道：上表除 `build_artifact_paths_missing`、`maintree_stray_wip_stale` 外，各信号告警为 `kind=ESCALATION`（经 freeze_for_human/升级告警入口成对写入），进前端告警区渲染下拉；`build_artifact_paths_missing` 与 `maintree_stray_wip_stale` 的发射点分别在 mergeback（`_maybe_signal_build_artifact_paths_missing`）与主树散件宽限升级（`worktree_manager/stray_wip.py`），写 `kind=SIGNAL` 记录（后者经 admin_monitor 三表登记接入 Administrator 自动唤起）——SIGNAL 记录不进前端告警区（`get_unhandled_alerts`/`AdminStore.unhandled()` 仅含 ESCALATION），其 choices 由 Administrator 处置契约消费。
- 发射点接线：预算耗尽与 token 告警（`budget.py` / `token_budget.py`）、升级闸门（`family.py`）、评审否决上限与评审器失败上限（`spec_review.py`）、judge 重跑上限（`judge_gate.py`）、同因重派熔断（`dispatch/queue.py`、`dispatch/fast_track.py`）、配置裁决（`mergeback.py`）、主树散件滞留升级（`worktree_manager/stray_wip.py`）写告警时同时写入 `choices` 字段；`admin_monitor.py`（SIGNAL 摄取侧与桶 0 发射侧）不携带。
- `maintree_stray_wip_stale` 落库记录自带 choices 快照（照 mergeback 先例），`recommended_action` 文案带出选项 id，并与 `admin_monitor.py` 的 SIGNAL_RECOMMENDATION 同文同步（防双处漂移）。
- 桶 0 知情/自愈类信号（`stale_code`、`transient_break_storm`、`run_infra_failure` 自动恢复、`run_cancelled`、误报类）不携带 `choices`，前端按「知道了」类渲染。
- `choices` 字段可缺省：无该字段的存量告警记录，读取与渲染路径兼容（按无选项处理）。
- 查询未注册的 signal_type 返回空选项集，不抛异常。
- 每个选项显式声明可选字段 `spec_scoped`：True=spec 作用域动作（动作语义针对具体 spec 的状态机，如 retry_review/force_advance/abandon），False=非作用域（不绑定具体 spec 状态机：确认/观察/写项目配置，乃至对主树工作区的受限 git 写如 commit_stray_wip）；字段缺省按 True 保守处理。可能全局形态的已注册桶，其选项集必须至少含一个非 spec_scoped 选项，否则全局信号下该桶选项永远无法执行。
- 全局形态判定单源 `is_global_spec`：spec 为 None/空串，或被占位符 `'global'` 顶替（`maintenance_runs` 以 `'global'` 占位空 spec；大小写与空白变体同判），对具体 spec 名判假。
- 解析单源 `resolve_choice(choice_id, signal_type)`：注册桶内精确匹配，未命中返回 `not-in-bucket`（不跨信号放行）→ signal_type 未注册时全表反查，spec_scoped 动作拒绝（`scoped-no-reverse`，不兜底放行）、非作用域动作返回拷贝 → 全表无此 id 返回 `unknown-choice`。执行器与消费端守卫共用本函数防解析漂移；返回选项为逐项拷贝，就地改写不污染注册表。
- `ack_self_heal`（确认自愈·继续观察，非作用域收口动作）声明在可能全局形态的 `build_artifact_paths_missing` 桶末位，未注册 signal_type 经全表反查可达，保证全局信号执行收口不断路。
- `commit_stray_wip` 是注册表中首个带主树 git 写副作用的动作：执行器以 signal_type 绑定守卫收口（仅受理 `maintree_stray_wip_stale`，未注册信号与姊妹 info 信号一律拒绝），未注册信号经全表反查通道可达本动作但不获执行授权（守卫细节见 [adjudication-choice-scope-guard](adjudication-choice-scope-guard.md)，执行语义见 [adjudication-actions](adjudication-actions.md)）。
- `untrack_stray_wip` 沿用同款双保险形态入桶（spec_scoped=False + 执行端 signal_type 绑定守卫仅收 `maintree_stray_wip_stale`），与 `commit_stray_wip` 同桶并存：提交适合交互会话遗留等应入库改动，根治适合被 track 的生成物类散件（每次构建必复发的确定性敞口）；二者的取舍由处置程序按复发计数判断（复发型处置义务见 [admin-choices-contract](admin-choices-contract.md)）。

## 溯源

- 2026-09-27 add-human-adjudication-choices（spec/archive/2026-09-27-add-human-adjudication-choices） — 建立静态注册表、告警 choices 字段契约与桶 0/桶 2 携带边界
- 2026-10-09 evo-fix-global-signal-choice-execution（spec/archive/2026-10-09-evo-fix-global-signal-choice-execution） — 选项新增 spec_scoped 作用域声明（缺省 True 保守）、is_global_spec 全局形态判定单源、resolve_choice 解析单源与 spec_scoped 反查收紧、ack_self_heal 全局收口动作入 build_artifact_paths_missing 桶
- 2026-10-08 evo-fix-env-exemption-exit-reachability（spec/archive/2026-10-08-fix-env-exemption-exit-reachability） — 新增 inconclusive_loop 裁决桶与 grant_env_exemption 授予 env 豁免选项（choices 闭环：告警下拉→alert-resolve→执行器，与 Administrator SIGNAL 通道并存）
- 2026-10-15 evo-fix-env-exemption-gate-conflict-and-scenario-revision-exit（spec/archive/2026-10-15-evo-fix-env-exemption-gate-conflict-and-scenario-revision-exit） — inconclusive_loop 桶新增 revise_scenario_reverify 修订场景·重验选项（JSON 载荷、夹具供给层路径白名单、修订上限默认 2 次超限冻结转人工）
- 2026-10-26 evo-add-commit-stray-wip-choice（spec/archive/2026-10-26-evo-add-commit-stray-wip-choice） — maintree_stray_wip_stale 桶新增 commit_stray_wip 提交散件选项（spec_scoped=False 全局作用域、与 stash 类动作互斥），为注册表首个主树 git 写动作；发射点 stray_wip 落库记录附 choices 快照、recommended_action 带出选项 id 并与 SIGNAL_RECOMMENDATION 同文同步
- 2026-10-27 evo-recurring-stray-remediation（spec/archive/2026-10-27-evo-recurring-stray-remediation） — maintree_stray_wip_stale 桶新增 untrack_stray_wip 根治·散件出库选项（git rm --cached + .gitignore 追加 + 独立提交），沿 commit_stray_wip 双保险形态（spec_scoped=False + 执行器 signal_type 绑定守卫），与提交选项同桶并存
