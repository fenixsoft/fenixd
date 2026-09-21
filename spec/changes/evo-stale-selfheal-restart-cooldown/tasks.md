## Deliverables

```yaml
- path: fenixd.py
  kind: modify
- path: core/config.py
  kind: modify
- path: tests/test_stale_selfheal_cooldown.py
  kind: new
```

## 1. 冷却机制实现

- [ ] 1.1 core/config.py：在 stale_code_selfheal config schema 中新增 cooldown_window_seconds（默认1800）、cooldown_threshold（默认3）、cooldown_duration_seconds（默认600）、self_triggered_window_seconds（默认300）、self_triggered_threshold（默认3）字段及默认值
- [ ] 1.2 core/fenixd.py `_maybe_stale_selfheal_tick`：在 in-flight 检查之后、_is_idle 之前，插入冷却状态检查——读取 .fenix/restart_history.jsonl（容错：文件不存在按空处理），统计窗口内重启次数，≥阈值则 reason=cooldown 并清零 idle 计时
- [ ] 1.3 core/fenixd.py `_maybe_stale_selfheal_tick`：成功触发重启（写入 restart_request）后，追加时间戳到 .fenix/restart_history.jsonl；每次 tick 入口清理 24 小时前的旧条目
- [ ] 1.4 core/fenixd.py `_maybe_stale_selfheal_tick`：触发重启前检测「自触发型 stale」——若距上次重启 < self_triggered_window_seconds，记 WARNING 日志且不写 restart_request；连续 self-triggered ≥ self_triggered_threshold 次时升级 admin 告警

## 2. _is_idle 补全

- [ ] 2.1 core/fenixd.py `_is_idle`：在 pm_engine._active_runs 检查之后，增加对 agent_runner._running_agents 的检查——若非空则返回 False

## 3. 测试

- [ ] 3.1 tests/test_stale_selfheal_cooldown.py：覆盖「窗口内重启 ≥ 阈值触发冷却」「冷却期间跳过触发」「自触发型 stale 识别与升级」「_is_idle 含 _running_agents 时返回 False」场景