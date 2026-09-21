# Design: Stale Selfheal 重启冷却机制

## 架构设计

在现有 `_maybe_stale_selfheal_tick`（fenixd.py:992-1081）流程中，在「检查 restart_request 是否存在（in-flight）」与「检查 _is_idle」之间插入冷却检查。

### 数据流

```
_maybe_stale_selfheal_tick 每秒调用
  │
  ├─ _code_stale == False → 清零恢复（现有逻辑不变）
  ├─ 阻断原因判定 → in-flight/disabled/unmanaged（现有逻辑不变）
  ├─ [NEW] 检查 restart_history.jsonl → 冷却中？
  │     └─ 窗口内重启 ≥ 阈值 → reason = "cooldown"，清零 idle 计时
  ├─ _is_idle() [修改：增加 _running_agents 检查]
  ├─ 累计空闲时长 ≥ confirm_seconds
  │     ├─ [NEW] 重启后 N 分钟内再检测 → self-triggered，记 WARNING
  │     └─ 正常触发 → 写 restart_request + 记录到 restart_history.jsonl
```

### 持久化

`.fenix/restart_history.jsonl`：每行一个 JSON 对象 `{"ts": "ISO8601"}`
- 写入时机：成功写入 restart_request 后追加
- 清理时机：`_maybe_stale_selfheal_tick` 入口处清理超过 24 小时的条目
- 格式保持 append-only，每次重启新追加一行

### 关键决策

1. **冷却检查位置**：在 in-flight 阻断之后、_is_idle 之前——避免影响正常的首次触发流程
2. **self-triggered 检测**：比较最近一次重启时间与当前时间差——若 < self_triggered_window 则标记
3. **向后兼容**：冷却阈值设为0或窗口设为0时等效关闭冷却

### 文件变更清单

- `core/fenixd.py`：修改 `_is_idle`（增加 _running_agents 检查）和 `_maybe_stale_selfheal_tick`（增加冷却逻辑）
- `core/config.py`：增加 stale_code_selfheal 配置字段的解析与默认值
- `tests/test_stale_selfheal_cooldown.py`：覆盖冷却触发、自触发识别、_is_idle 补全