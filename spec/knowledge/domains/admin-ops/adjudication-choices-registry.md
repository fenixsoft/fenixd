<!-- knowledge: capability=adjudication-choices-registry rev=3
     sources=spec/archive/2026-09-27-add-human-adjudication-choices,spec/archive/2026-10-09-evo-fix-global-signal-choice-execution,spec/archive/2026-10-08-fix-env-exemption-exit-reachability,spec/archive/2026-10-15-evo-fix-env-exemption-gate-conflict-and-scenario-revision-exit -->

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

- 消费通道：上表除 `build_artifact_paths_missing` 外，各信号告警为 `kind=ESCALATION`（经 freeze_for_human/升级告警入口成对写入），进前端告警区渲染下拉；`build_artifact_paths_missing` 的发射点在 mergeback（`_maybe_signal_build_artifact_paths_missing`），写 `kind=SIGNAL` 记录——SIGNAL 记录不进前端告警区（`get_unhandled_alerts`/`AdminStore.unhandled()` 仅含 ESCALATION），其 choices 由 Administrator 处置契约消费。
- 发射点接线：预算耗尽与 token 告警（`budget.py` / `token_budget.py`）、升级闸门（`family.py`）、评审否决上限与评审器失败上限（`spec_review.py`）、judge 重跑上限（`judge_gate.py`）、同因重派熔断（`dispatch/queue.py`、`dispatch/fast_track.py`）、配置裁决（`mergeback.py`）写告警时同时写入 `choices` 字段；`admin_monitor.py`（SIGNAL 摄取侧与桶 0 发射侧）不携带。
- 桶 0 知情/自愈类信号（`stale_code`、`transient_break_storm`、`run_infra_failure` 自动恢复、`run_cancelled`、误报类）不携带 `choices`，前端按「知道了」类渲染。
- `choices` 字段可缺省：无该字段的存量告警记录，读取与渲染路径兼容（按无选项处理）。
- 查询未注册的 signal_type 返回空选项集，不抛异常。
- 每个选项显式声明可选字段 `spec_scoped`：True=spec 作用域动作（动作语义针对具体 spec 的状态机，如 retry_review/force_advance/abandon），False=非作用域（仅确认/观察/写项目配置，不触碰任何 spec 状态机）；字段缺省按 True 保守处理。可能全局形态的已注册桶，其选项集必须至少含一个非 spec_scoped 选项，否则全局信号下该桶选项永远无法执行。
- 全局形态判定单源 `is_global_spec`：spec 为 None/空串，或被占位符 `'global'` 顶替（`maintenance_runs` 以 `'global'` 占位空 spec；大小写与空白变体同判），对具体 spec 名判假。
- 解析单源 `resolve_choice(choice_id, signal_type)`：注册桶内精确匹配，未命中返回 `not-in-bucket`（不跨信号放行）→ signal_type 未注册时全表反查，spec_scoped 动作拒绝（`scoped-no-reverse`，不兜底放行）、非作用域动作返回拷贝 → 全表无此 id 返回 `unknown-choice`。执行器与消费端守卫共用本函数防解析漂移；返回选项为逐项拷贝，就地改写不污染注册表。
- `ack_self_heal`（确认自愈·继续观察，非作用域收口动作）声明在可能全局形态的 `build_artifact_paths_missing` 桶末位，未注册 signal_type 经全表反查可达，保证全局信号执行收口不断路。

## 溯源

- 2026-09-27 add-human-adjudication-choices（spec/archive/2026-09-27-add-human-adjudication-choices） — 建立静态注册表、告警 choices 字段契约与桶 0/桶 2 携带边界
- 2026-10-09 evo-fix-global-signal-choice-execution（spec/archive/2026-10-09-evo-fix-global-signal-choice-execution） — 选项新增 spec_scoped 作用域声明（缺省 True 保守）、is_global_spec 全局形态判定单源、resolve_choice 解析单源与 spec_scoped 反查收紧、ack_self_heal 全局收口动作入 build_artifact_paths_missing 桶
- 2026-10-08 evo-fix-env-exemption-exit-reachability（spec/archive/2026-10-08-fix-env-exemption-exit-reachability） — 新增 inconclusive_loop 裁决桶与 grant_env_exemption 授予 env 豁免选项（choices 闭环：告警下拉→alert-resolve→执行器，与 Administrator SIGNAL 通道并存）
- 2026-10-15 evo-fix-env-exemption-gate-conflict-and-scenario-revision-exit（spec/archive/2026-10-15-evo-fix-env-exemption-gate-conflict-and-scenario-revision-exit） — inconclusive_loop 桶新增 revise_scenario_reverify 修订场景·重验选项（JSON 载荷、夹具供给层路径白名单、修订上限默认 2 次超限冻结转人工）
