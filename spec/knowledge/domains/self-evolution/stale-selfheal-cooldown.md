<!-- knowledge: capability=stale-selfheal-cooldown rev=1 sources=spec/archive/2026-09-25-evo-stale-selfheal-restart-cooldown -->

# 自愈重启冷却与自触发升级

陈旧自愈的连续重启保护：滑动窗口计数进入冷却锁存，重启后短期复现的陈旧只告警不再重启，防「重启→检测→重启」正反馈循环。

## 现行规则

- 重启历史账本：每次自愈重启向 `.fenix/restart_history.jsonl` 追加 `{"ts": ISO8601, "self_triggered": bool, "self_triggered_streak": int}`；超过 24 小时的条目自动清理；文件缺失或行损坏按空处理，不阻断自愈。
- 滑动窗口冷却锁存：触发前检查滑动窗口（`cooldown_window_seconds`，缺省 1800 秒）内重启次数，达 `cooldown_threshold`（缺省 3 次）即进入冷却；冷却自首次进入时刻锁存 `cooldown_duration_seconds`（缺省 600 秒）——锁存期内即使窗口计数因条目老化回落到阈值之下，仍保持冷却状态。
- 冷却期行为：`_maybe_stale_selfheal_tick` 跳过触发、原因标记 `cooldown`，并清零空闲计时；INFO 日志仅在状态边沿记一次，不逐 tick 刷屏；冷却期间陈旧告警仍保持显示（仅跳过触发重启）。冷却首次进入（边沿）升级为 admin 告警：经 `admin_store.append` 落 `signal_type: stale_selfheal_cooldown`、`severity: warning`；不复用 `stale_code` 类型——该类型写入即自动 mark_handled，复用会被当已处置吞掉。
- 自触发型 stale 识别：重启后 `self_triggered_window_seconds`（缺省 300 秒）内再次检测到 stale 视为 self-triggered，仅记 WARNING 日志、不写 restart_request。streak 计数以「重启周期」为单位（同一进程内多次 tick 只计一次）并持久化到 restart_history.jsonl：距上次重启 ≥ 自触发窗口的过期重启使 streak 归零，自触发窗口内的重启使 streak +1（只放进程内存则阈值恒不可达——每次自触发都伴随一次重启、新进程归零）。streak 达 `self_triggered_threshold`（缺省 3 次）升级为 admin 告警：`signal_type: stale_selfheal_loop`、`severity: critical`。
- 空闲判定补全：`_is_idle` 检查 `agent_runner._running_agents`（`getattr` 链读取 `getattr(getattr(self, "agent_runner", None), "_running_agents", None) or {}`），任一 run 在飞返回 False；缺属性/None 视为该维度为空，不抛异常（`_is_idle` 已有「异常按非空闲」策略，抛异常会把缺属性态误判为非空闲）。依据：spec-review 评审 run 不占 `pm_engine._active_runs`（评审条目独立登记于 `_active_reviews`），缺此检查则空闲判定对在飞评审不可见、自愈重启会杀掉评审中途的 run。
- 配置：五键挂于 `stale_code_selfheal` 配置节——`cooldown_window_seconds`=1800、`cooldown_threshold`=3、`cooldown_duration_seconds`=600、`self_triggered_window_seconds`=300、`self_triggered_threshold`=3；经 `.fenix/config.yaml` 文件配置 + 30s 热更新生效；非正整数回退缺省、bool 陷阱显式排除（`isinstance(True, int)` 为真）、不抛异常；冷却无独立开关，`0` 不等效关闭。本能力不扩展 Dashboard 面板与 `/api/config` 写白名单（该节为键级白名单合并，面板保存既写不进新键也不会清除文件侧新键）。
- 总开关：`stale_code_selfheal.enabled: false` 时全部冷却机制不生效（向后兼容）。

## 溯源

- 2026-09-25 evo-stale-selfheal-restart-cooldown — 新增滑动窗口重启冷却锁存、自触发 stale 识别与 streak 升级告警、_is_idle 纳入 _running_agents（治正反馈循环：单日 47 分钟 27 次重启、全天 93 次并杀死在飞评审 run）
