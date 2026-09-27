<!-- knowledge: capability=settings-system-tab rev=1 sources=spec/archive/2026-09-11-add-settings-system-tab -->

# 设置页系统页签（admin 配置）

设置页「系统」页签展示并编辑 `admin.*` 运维配置键，读写经既有受管白名单通道闭环。

## 规则

- 设置页「系统」页签（SystemPanel）展示并允许编辑 5 个 `admin.*` 键，每项附一句话注解：`admin.enabled`（Switch）、`admin.interval_minutes`（数字输入，正数）、`admin.escalation_cooldown_minutes`（数字输入，非负数）、`admin.merge_breaker_threshold`（数字输入，正整数）、`admin.shutdown_drain_seconds`（数字输入，非负整数，0=快速停机）。
- 读写闭环：`read_config` 将 admin 段纳入受管白名单（返回 5 键当前值，含缺省值）；设置页保存经既有 `write_config` 通道写回项目级 `.fenix/config.yaml` 并刷新回显；白名单扩展不改变既有 llm / agents / verify 段的返回结构。
- 写入校验：布尔键须为 bool、interval_minutes 正数、escalation_cooldown_minutes 非负数、merge_breaker_threshold 正整数、shutdown_drain_seconds 非负整数；非法输入拒绝保存并返回明确错误（沿用既有错误返回形态），配置文件不被写入。
- 新项目配置模板 `admin.shutdown_drain_seconds` 默认值为 0（快速停机 + interrupted 标记续做兜底），避免 1-2 小时级 implementer/planner 在飞场景每次重启等满排水窗口；注释说明 0 值语义与 resume 兜底路径。
- admin 段键的说明（含排水窗口「daemon 排水 / supervisor 强杀等待 = 值 + 120s」的双侧行为与 0 值语义）记录于 `docs/help/08-config.md`，与模板注解一致。

## 溯源

- 2026-09-11 add-settings-system-tab — 新增设置页系统页签与 admin 段读写白名单闭环、写入校验、模板 shutdown_drain_seconds 默认值改 0 与文档同步
