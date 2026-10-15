## MODIFIED Requirements

### Requirement: 周期窗口与自省同源

需求题名沿用基线（add-code-review-agent-and-quality-tab 立项、add-code-review-scope-config 改写）。本变更将「同源」收窄为「缺省回退自省」：触发时点与窗口水位均可独立于自省，未显式配置/无自身水位时回退自省＝历史行为逐位一致。scope 双档（window/full）与既有调度守卫全部保留，仅触发时点与 window 档水位两处改源。

- 触发时点 MUST 读独立配置键 `admin.code_review.run_at`（本地时间 HH:MM）；该键缺失或非法时 MUST 回退 `admin.self_review.run_at`（缺省＝历史行为，向后兼容）。回退解析由 `ConfigLoader.get_code_review_config` 单源完成，检查点 MUST NOT 二次解析。
- `admin.code_review.scope` 取值 `window` | `full` 不变；非法值（含缺失/类型错误）MUST 回退 `window`，行为与历史版本逐字节一致。
- scope=`window`（缺省）：审查窗口水位 MUST 由审查车道自身承载——调度收尾将本轮审查完成时刻写入 `.fenix/code_review_state.json` 的 `last_run_at`（aware ISO8601 本地时区表述，与 `self_review_state.last_run_at` 一致，`_iso_to_aware_dt` 直读）；`compute_window` 计算 `window_start` MUST 优先读该字段，字段缺失（首跑/存量状态）MUST 回退读 `.fenix/self_review_state.json` 的 `last_run_at`，再缺失回退 `now - 24h`（既有口径不变）。`window_kind` 映射不变：读到任一 `last_run_at`（审查自身或自省回退）返回 `last_run`，双缺失回退 24h 返回 `fallback`。窗口内审查对象定义不变：`window_start` 之后合并/产出到主树的 SPEC 所变更的文件集合。
- scope=`full`：审查对象 MUST 为全仓受控源码文件（`collect_manifest(scope="full")`），`window_start` 以 None 参与 run（manifest 审计字段如实记录 `full`）；`max_files` 上限 MUST 同样生效；触发时点同读独立键 `admin.code_review.run_at`。
- 调度守卫 MUST 与自省一致：同一自然日不重复触发；未到生效 `run_at` 不触发；单飞判定不变；`admin.code_review.enabled` 为 false 时全链路零动作（不派发、不写产物）；`review_kind` 保持 `scheduled`。
- 巡检循环中 code-review 检查点 MUST 仍先于自省检查点执行（自省收尾覆写自身 `last_run_at` 的既有约束，与触发时点解耦正交）。

#### Scenario: 独立时点生效且互不连带

- **WHEN** `admin.code_review.run_at` 配置为 "13:00"、`admin.self_review.run_at` 为 "01:00"
- **THEN** 自省检查点 01:00 照常触发；code-review 检查点在 01:00 巡检轮返回 `reason=before_run_at` 不派发；13:00 后巡检轮 code-review 正常派发且不触发自省

#### Scenario: 缺省回退等于历史行为

- **WHEN** 配置中不存在 `admin.code_review.run_at` 键
- **THEN** 生效触发时点恰为 `admin.self_review.run_at`，与解耦前行为逐位一致

#### Scenario: 非法值回退

- **WHEN** `admin.code_review.run_at` 为 "abc"、`123`、"25:00" 等非法值
- **THEN** 回退 `admin.self_review.run_at`，巡检路径不因脏值中断（对齐 scope 回退口径）

#### Scenario: 窗口水位优先审查自身

- **WHEN** code-review 以独立时点 13:00 完成过至少一轮（state 含 `last_run_at`），自省 01:00 已覆写自身 `last_run_at`
- **THEN** 下一轮窗口 `window_start` 取 code-review 自身 `last_run_at`，两轮审查之间的全部变更被覆盖，不因自省先跑而出现覆盖缺口

#### Scenario: 窗口水位回退现状

- **WHEN** `code_review_state.json` 无 `last_run_at`（存量状态或首跑）
- **THEN** `window_start` 取自省 `last_run_at`（再缺失回退 `now - 24h`），与现状路径逐位一致

#### Scenario: scope=full 在独立时点下照常收全仓

- **WHEN** `admin.code_review.scope` 为 `full` 且 `admin.code_review.run_at` 为 "13:00"
- **THEN** 13:00 后巡检轮按 `collect_manifest(scope="full")` 收集全仓并经 `max_files` 截断，`window_start=None`、`review_kind="scheduled"`；与缺省时点行为仅触发时刻不同

#### Scenario: 非法 scope 回退窗口模式

- **WHEN** `admin.code_review.scope` 为 `"today"`（非法值）
- **THEN** 周期触发 MUST 按 scope=`window` 执行（水位与触发时点按本需求条款），MUST NOT 报错中断巡检

#### Scenario: 开关关闭零动作

- **WHEN** `admin.code_review.enabled` 为 false（任意 scope 与 `run_at` 取值）
- **THEN** 到达生效时点 MUST NOT 派发 code-review run、MUST NOT 写任何 code-review 产物
