# transient-controls-ui — 瞬断治理配置的设置界面

## ADDED Requirements

### Requirement: Settings 面板展示与编辑瞬断治理配置

Dashboard Settings 页 SystemPanel MUST 新增「瞬断治理」分组，展示并允许编辑以下配置键，语义与 `core/config.py` 定义一致：`agents.transient_backoff_schedule`（逗号分隔秒序列）、`agents.transient_redispatch_delay_seconds`、`agents.transient_break_threshold`、`agents.transient_break_window_seconds`、`agents.transient_break_cooldown_seconds`。输入校验与后端一致（非负整数 / 逗号分隔序列），非法输入禁止保存并提示。

#### Scenario: 配置项展示与修改保存

- **GIVEN** 用户打开 Settings 页 SystemPanel
- **WHEN** 修改 `transient_break_threshold` 为 5 并保存
- **THEN** 保存成功且界面回显 5；配置文件中对应键更新为 5

#### Scenario: 非法输入拦截

- **GIVEN** 用户在 `transient_redispatch_delay_seconds` 输入 `-5` 或非数字
- **WHEN** 尝试保存
- **THEN** 保存被拦截并展示校验错误，配置文件不被写入

#### Scenario: 保存后热更新生效

- **GIVEN** 配置保存成功
- **WHEN** daemon 的 30 秒 mtime 热更新检测周期过后
- **THEN** 新配置值在 runner 派发与 dispatch 闸门判定中生效，无需重启 daemon
