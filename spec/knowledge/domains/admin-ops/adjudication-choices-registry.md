<!-- knowledge: capability=adjudication-choices-registry rev=1 sources=spec/archive/2026-09-27-add-human-adjudication-choices -->

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
| `redispatch_loop_detected` | continue_auto_fix（解冻+清同因计数）/ manual_fixed_reverify / force_advance / abandon |
| `spec-review-rejected`（评审否决达上限） | revise_reproposal（按否决意见改方案重评）/ force_advance / abandon |
| `spec-review-incomplete`（评审器连坏） | retry_review（解冻重派评审）/ skip_review_gate / abandon |
| `token_budget` | ignore（知情确认）/ freeze_stop_loss（冻结止损）/ raise_budget（调大预算） |
| `build_artifact_paths_missing` | open_config（引导到配置表单）/ declare_no_artifacts（声明无产物） |

- 消费通道：上表除 `build_artifact_paths_missing` 外，各信号告警为 `kind=ESCALATION`（经 freeze_for_human/升级告警入口成对写入），进前端告警区渲染下拉；`build_artifact_paths_missing` 的发射点在 mergeback（`_maybe_signal_build_artifact_paths_missing`），写 `kind=SIGNAL` 记录——SIGNAL 记录不进前端告警区（`get_unhandled_alerts`/`AdminStore.unhandled()` 仅含 ESCALATION），其 choices 由 Administrator 处置契约消费。
- 发射点接线：预算耗尽与 token 告警（`budget.py` / `token_budget.py`）、升级闸门（`family.py`）、评审否决上限与评审器失败上限（`spec_review.py`）、judge 重跑上限（`judge_gate.py`）、同因重派熔断（`dispatch/queue.py`、`dispatch/fast_track.py`）、配置裁决（`mergeback.py`）写告警时同时写入 `choices` 字段；`admin_monitor.py`（SIGNAL 摄取侧与桶 0 发射侧）不携带。
- 桶 0 知情/自愈类信号（`stale_code`、`transient_break_storm`、`run_infra_failure` 自动恢复、`run_cancelled`、误报类）不携带 `choices`，前端按「知道了」类渲染。
- `choices` 字段可缺省：无该字段的存量告警记录，读取与渲染路径兼容（按无选项处理）。
- 查询未注册的 signal_type 返回空选项集，不抛异常。

## 溯源

- 2026-09-27 add-human-adjudication-choices — 建立静态注册表、告警 choices 字段契约与桶 0/桶 2 携带边界
