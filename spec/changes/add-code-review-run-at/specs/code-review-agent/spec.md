## MODIFIED Requirements

### Requirement: 周期窗口与自省同源

- 触发时点 MUST 读独立配置键 `admin.code_review.run_at`（本地时间 HH:MM）；该键缺失或非法时 MUST 回退 `admin.self_review.run_at`（缺省＝历史行为，向后兼容）。回退解析由 `ConfigLoader.get_code_review_config` 单源完成，检查点 MUST NOT 二次解析。
- 审查窗口水位 MUST 由审查车道自身承载：调度收尾将本轮审查完成时刻写入 `.fenix/code_review_state.json` 的 `last_run_at`（aware ISO8601 UTC）；`compute_window` 计算 `window_start` MUST 优先读该字段，字段缺失（首跑/存量状态）MUST 回退读 `.fenix/self_review_state.json` 的 `last_run_at`，再缺失回退 `now - 24h`（既有口径不变）。
- 调度守卫 MUST 与自省一致：同一自然日不重复触发；未到生效 `run_at` 不触发；`admin.code_review.enabled` 为 false 时全链路零动作（不派发、不写产物）。
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
