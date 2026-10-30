# agent.harness 全局开关

<!-- knowledge: capability=harness-config rev=1
     sources=spec/archive/2026-10-30-add-harness-adapter-layer -->

harness 选型的唯一配置开关：一个全局键决定全部车道经哪个 adapter 派发，配置读侧容错、派发边界显性爆炸（禁静默代跑）。

## 规则

- **键与取值**：config 支持 `agent.harness` 键，合法值 `claude|dsh`，缺省 `claude`；项目级与用户级双层深合并语义与既有配置键一致。非法值解析回退 `claude` 并产生含「不支持」字样的告警日志，daemon 不中断。
- **健康检查门控**：选定值经 dispatch 前置健康检查验证对应 adapter 可用（dsh 通道：`dsh --version` 在白名单且 Bundle 可挂载，见 [dsh-harness-integration](dsh-harness-integration.md)）；检查不通过时 dispatch 以明确错误失败（含修复指引），MUST NOT 静默回退 claude 代跑——配置读侧容错与工厂/dispatch 拒绝静默代跑分层，错误配置在派发边界显性爆炸（ADR-271）。
- **热重载生效语义**：沿用 30s mtime 热重载机制；harness 切换自下次 dispatch 起生效，在飞 run 不受影响。
- **界面同步**：Dashboard 设置页系统级面板提供 `agent.harness` 的查看与修改，保存走 settings_routes 并受同一校验约束（校验不过保存被拦、配置值不变）；`config.template.yaml` 含该键注释说明——配置键与设置界面能力同步存在。

## 关键行为

缺省路径零感知：config.yaml 不含该键时全部车道经 claude adapter 派发，行为与单 harness 时代一致。切换路径：设置页或 config 修改 → 热重载 → 下次 dispatch 前健康检查 → 全链走目标 adapter。

## 溯源

- 2026-10-30 add-harness-adapter-layer（spec/archive/2026-10-30-add-harness-adapter-layer） — 新增本能力：agent.harness 校验/缺省/非法值回退告警、SystemPanel + settings_routes 界面同步、热重载对下次 dispatch 生效语义、dsh 值部署前 fail-fast 拦截（后随 dsh-harness-integration 健康检查落地兑现为可用值）
