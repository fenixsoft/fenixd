## ADDED Requirements

### Requirement: 裁决选项静态注册表

系统 MUST 提供静态裁决选项注册表（新建 `core/dashboard/data/adjudication_choices.py`），按 `signal_type` 映射到裁决选项集。每个选项 MUST 包含 `id`（稳定字符串）、`label`（中文短标签）、`desc`（一句话说明执行内容）、`action`（映射的后端动作标识，复用既有动词或新增动词）。注册表 MUST 为纯静态声明（模块常量或常量函数），MUST NOT 依赖 LLM 生成。

初始覆盖（桶 2 真裁决类）：

| signal_type | 必须提供的选项（id 语义） |
|---|---|
| `impl_budget_exhausted` | continue_auto_fix（解冻+调大预算继续）/ manual_fixed_reverify（人工已修复，重置验证重跑）/ force_advance（接受现状收尾推进）/ abandon（撤销丢弃） |
| `judge_rerun_cap` | manual_fixed_reverify / force_advance / abandon |
| `verify_fail_escalation`（验证失败升级闸门冻结，`_verify_fail_rounds` 达阈值触发，发射于 family.py） | continue_auto_fix（解冻+重置失败轮计数）/ manual_fixed_reverify / force_advance / abandon |
| `redispatch_loop_detected` | continue_auto_fix（解冻+清同因计数）/ manual_fixed_reverify / force_advance / abandon |
| `spec-review-rejected`（评审否决达上限，方向不成立冻结，发射于 spec_review.py） | revise_reproposal（按否决意见改方案重评）/ force_advance / abandon |
| `spec-review-incomplete`（评审器连坏） | retry_review（解冻重派评审）/ skip_review_gate / abandon |
| `token_budget` | ignore（知情确认）/ freeze_stop_loss（冻结止损）/ raise_budget（调大预算） |
| `build_artifact_paths_missing` | open_config（引导到配置表单）/ declare_no_artifacts（声明无产物） |

消费通道约定：上表除 `build_artifact_paths_missing` 外，各信号的告警记录均为 `kind=ESCALATION`（经 `freeze_for_human`/升级告警入口成对写入），进前端告警区渲染下拉。`build_artifact_paths_missing` 的发射点在 `core/worktree_manager/mergeback.py`（`_maybe_signal_build_artifact_paths_missing`），写 `kind=SIGNAL` 记录——SIGNAL 记录不进前端告警区（`get_unhandled_alerts`/`AdminStore.unhandled()` 仅含 ESCALATION），其 choices 由 Administrator 处置契约消费（见 admin-choices-contract），不经前端下拉渲染。

#### Scenario: 注册表按信号类型返回选项
- **WHEN** 查询 `signal_type=impl_budget_exhausted` 的裁决选项
- **THEN** 返回的选项集包含 continue_auto_fix、manual_fixed_reverify、force_advance、abandon 四项，每项均含 id/label/desc/action 四字段且 id 在同信号内唯一

#### Scenario: 未注册信号返回空集
- **WHEN** 查询注册表中不存在的 signal_type（如 `stale_code`）
- **THEN** 返回空选项集，不抛异常

### Requirement: 告警记录携带 choices 字段

桶 2 信号的发射点（`core/pm_engine/budget.py` 预算耗尽与 token 告警、`core/pm_engine/family.py` 升级闸门、`core/pm_engine/spec_review.py` 评审否决上限与评审器失败上限、`core/pm_engine/verification/judge_gate.py` judge 重跑上限、`core/pm_engine/dispatch/queue.py` 与 `core/pm_engine/dispatch/fast_track.py` 同因重派熔断、`core/agent_runner/token_budget.py` token 预算、`core/worktree_manager/mergeback.py` 配置裁决）写 `admin_alerts.json` 记录时 MUST 同时写入 `choices` 字段（取自注册表；`core/admin_monitor.py` 为 SIGNAL 摄取侧与桶 0 发射侧，仅按桶 0 约定确认不携带）。桶 0 知情/自愈类信号（`stale_code`、`transient_break_storm`、`run_infra_failure` 自动恢复、`run_cancelled`、误报类）MUST NOT 携带 `choices`。`choices` 字段 MUST 可缺省：无该字段的存量告警记录读取路径 MUST 兼容（按无选项处理）。

#### Scenario: 真裁决告警携带选项
- **WHEN** 实现预算耗尽触发冻结并写入告警记录
- **THEN** 该记录含非空 `choices` 数组，选项内容与注册表 `impl_budget_exhausted` 一致

#### Scenario: 知情类告警不携带选项
- **WHEN** `stale_code` 信号写入告警记录
- **THEN** 该记录不含 `choices` 字段（或为空），前端按「知道了」类渲染

#### Scenario: 存量无字段告警兼容
- **WHEN** 读取历史告警记录（无 `choices` 字段）
- **THEN** 读取与渲染路径不报错，该告警按无选项告警展示
