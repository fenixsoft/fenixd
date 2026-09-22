# code-review-agent 规格（scope 可配置扩展）

## MODIFIED Requirements

### Requirement: 周期窗口与自省同源

code-review 的审查周期 SHALL 与每日自省（`admin.self_review`）完全同源，MUST NOT 另立一套周期口径。审查范围 SHALL 经 `admin.code_review.scope` 可配置，`window`（缺省）与 `full` 两档共用同一套调度守卫。

- `admin.code_review.scope` 取值 `window` | `full`；非法值（含缺失/类型错误）MUST 回退 `window`，行为与历史版本逐字节一致。
- scope=`window`（缺省）：审查窗口 MUST 取 `.fenix/self_review_state.json` 的 `last_run_at`；无 `last_run_at`（首跑/旧格式）MUST 回退 `now - 24h`；窗口内审查对象 MUST 为 `window_start` 之后合并/产出到主树的 SPEC 所变更的文件集合。
- scope=`full`：审查对象 MUST 为全仓受控源码文件（`collect_manifest(scope="full")`），`window_start` 以 None 参与 run（manifest 审计字段如实记录 `full`）；`max_files` 上限 MUST 同样生效。
- 两档共用：触发时点与自省时点对齐（`run_at`）；同一自然日不重复触发；单飞判定；`admin.code_review.enabled` 为 false 时全链路零动作；`review_kind` 保持 `scheduled`。

#### Scenario: 窗口起点取上次自省时刻（scope=window，缺省）

- **WHEN** `admin.code_review.scope` 缺失或为 `window`，`.fenix/self_review_state.json` 的 `last_run_at` 为 `T0`，当前触发 code-review
- **THEN** 审查窗口 MUST 为 `[T0, now]`，审查对象 MUST 为 `T0` 之后合并的 SPEC 所变更文件

#### Scenario: 首跑回退 24 小时

- **WHEN** scope=`window` 且 `.fenix/self_review_state.json` 无 `last_run_at` 字段
- **THEN** 审查窗口 MUST 为 `[now - 24h, now]`

#### Scenario: scope=full 收集全仓并保持审计口径

- **WHEN** `admin.code_review.scope` 为 `full` 且周期触发到达（守卫全部通过）
- **THEN** manifest MUST 按 `collect_manifest(scope="full")` 收集全仓受控源码文件并经 `max_files` 截断，`run_code_review` 以 `scope="full"`、`window_start=None`、`review_kind="scheduled"` 派发
- **AND** 台账记录的 `review_kind` 仍为 `scheduled`，manifest 内 scope 审计字段为 `full`

#### Scenario: 非法 scope 回退窗口模式

- **WHEN** `admin.code_review.scope` 为 `"today"`（非法值）或非字符串类型
- **THEN** 周期触发 MUST 按 scope=`window` 执行（窗口同源自省），MUST NOT 报错中断巡检

#### Scenario: 开关关闭零动作

- **WHEN** `admin.code_review.enabled` 为 false（任意 scope 取值）
- **THEN** 到达自省时点 MUST NOT 派发 code-review run、MUST NOT 写任何 code-review 产物

### Requirement: 设置页审查范围配置

设置页「质量」页签「周期性代码审查」区块 SHALL 提供「审查范围」下拉（`当期审查` / `全库审查`），与项目页「代码审查」分面手动触发按钮（当期审查 / 全库审查）语义对应。

- 下拉取值映射 `admin.code_review.scope`（`当期审查→window`、`全库审查→full`）；配置缺失回显 `window`。
- 保存走既有设置页配置写入链（`admin.code_review` 受管段），随既有保存按钮一并落盘。

#### Scenario: 配置缺失回显缺省

- **WHEN** 配置中无 `admin.code_review.scope` 键，用户打开设置页质量页签
- **THEN** 下拉回显「当期审查」（window）

#### Scenario: 切换为全库审查并保存

- **WHEN** 用户把下拉切到「全库审查」并保存
- **THEN** `admin.code_review.scope` 落盘为 `full`，次日周期触发按全仓收集执行
