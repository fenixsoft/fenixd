## ADDED Requirements

### Requirement: 场景争议升级信号的裁决选项覆盖

注册表 MUST 为场景争议类升级会流经的信号 `manual-intervention` 与 `verify_env_blocked` 各登记裁决选项集，且两桶 MUST 含场景修订重验出口 `revise_scenario_reverify`（`spec_scoped=true`、`requires_payload=true`，字段与 `inconclusive_loop` 桶逐字一致，经模块级单源常量按引用复用）。该出口在两信号上经 `resolve_choice` 桶内精确解析 MUST 可达——Administrator 自动处置通道不再因 scoped-no-reverse 被拒。未注册 signal_type 的全表反查收紧（scoped-no-reverse）MUST 维持不变。

#### Scenario: Administrator 自动处置可达场景修订出口
- **WHEN** 一条 signal_type=verify_env_blocked 的升级告警，其处置记录携带 choice_id=revise_scenario_reverify 与合法 choice_payload JSON
- **THEN** resolve_choice 桶内精确命中并返回 requires_payload=true 的选项，执行器落场景修订与 re-entry 重验，不再返回 scoped-no-reverse 拒绝

#### Scenario: manual-intervention 信号同样命中且三桶单源
- **WHEN** resolve_choice("revise_scenario_reverify", "manual-intervention")
- **THEN** 返回选项拷贝与空拒绝原因，且 inconclusive_loop / manual-intervention / verify_env_blocked 三桶解析结果逐项相等

#### Scenario: 守卫不回退
- **WHEN** 以未注册 signal_type 解析 revise_scenario_reverify
- **THEN** 仍返回 (None, "scoped-no-reverse")，全表反查收紧语义与注册前一致

#### Scenario: 跨桶一致性在 import 期钉死
- **WHEN** 任一桶内该选项的 action/spec_scoped/destructive/requires_payload 与其他桶漂移
- **THEN** 模块 import 即抛 AssertionError（_assert_registry_consistency），不留给运行期静默漂移
