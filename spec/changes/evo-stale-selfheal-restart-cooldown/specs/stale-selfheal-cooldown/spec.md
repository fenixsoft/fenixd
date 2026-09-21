# Spec: Stale Selfheal 重启冷却机制

## 功能需求

### FR-1: 滑动窗口重启计数
- 维护 `.fenix/restart_history.jsonl`，每次重启记录 ISO 时间戳
- `_maybe_stale_selfheal_tick` 触发前检查：30 分钟（可配置）窗口内重启次数
- 窗口内重启 ≥3 次（可配置）时进入冷却状态

### FR-2: 冷却状态行为
- 冷却期间 `_maybe_stale_selfheal_tick` 跳过触发，原因标记为 `cooldown`
- 冷却持续 10 分钟（可配置），期间记录 INFO 日志
- 冷却触发时升级为 admin 告警（severity: warning）

### FR-3: 自触发型 stale 识别
- 重启后 5 分钟（可配置）内若再次检测到 stale，视为 self-triggered
- self-triggered stale 仅记录 WARNING 日志，不写 restart_request
- self-triggered 连续 3 次后升级为 admin 告警（severity: critical）

### FR-4: _is_idle 补全
- 在 `_is_idle` 中增加对 agent_runner._running_agents 的检查
- 若任一 run 在飞则返回 False

## 接口设计

配置字段（stale_code_selfheal config 下）：
- `cooldown_window_seconds`: 滑动窗口时长，默认 1800（30 分钟）
- `cooldown_threshold`: 窗口内重启次数阈值，默认 3
- `cooldown_duration_seconds`: 冷却持续时长，默认 600（10 分钟）
- `self_triggered_window_seconds`: 自触发检测窗口，默认 300（5 分钟）
- `self_triggered_threshold`: 自触发升级阈值，默认 3

## 行为规范

- 配置 disabled 时所有冷却机制不生效（向后兼容）
- restart_history.jsonl 超过 24 小时的条目自动清理
- 冷却期间陈旧告警仍保持显示（仅跳过触发重启）