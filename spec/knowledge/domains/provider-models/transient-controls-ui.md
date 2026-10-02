<!-- knowledge: capability=transient-controls-ui rev=1 sources=spec/archive/2026-09-13-fix-provider-transient-backoff -->

# 瞬断治理配置界面

设置页「瞬断治理」分组暴露瞬断退避与全局熔断的全部治理键，改后经热更新生效、无需重启。

## 规则

- Settings 页 SystemPanel「瞬断治理」分组展示并允许编辑 5 个配置键，语义与 `core/config.py` 定义一致：`agents.transient_backoff_schedule`（逗号分隔秒序列）、`agents.transient_redispatch_delay_seconds`、`agents.transient_break_threshold`、`agents.transient_break_window_seconds`、`agents.transient_break_cooldown_seconds`。
- 输入校验与后端一致（非负整数 / 逗号分隔序列），非法输入禁止保存并提示校验错误，配置文件不被写入。
- 保存成功后经 daemon 的 30 秒 mtime 热更新检测周期生效：新配置值作用于 runner 派发与 dispatch 闸门判定，无需重启 daemon。
- 各键被消费的运行时语义见 [provider-transient-backoff](provider-transient-backoff.md) 与 [transient-dispatch-gating](transient-dispatch-gating.md)。

## 溯源

- 2026-09-13 fix-provider-transient-backoff（spec/archive/2026-09-13-fix-provider-transient-backoff） — 新增瞬断治理配置分组，覆盖退避表、重派延迟与全局熔断窗口/阈值/冷却 5 键的展示、校验与热更新生效契约
