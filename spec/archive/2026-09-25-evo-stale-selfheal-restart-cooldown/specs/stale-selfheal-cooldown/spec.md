# Spec: Stale Selfheal 重启冷却机制

## 功能需求

### FR-1: 滑动窗口重启计数与冷却锁存
- 维护 `.fenix/restart_history.jsonl`，每次自愈重启追加一条
  `{"ts": ISO8601, "self_triggered": bool, "self_triggered_streak": int}`
- `_maybe_stale_selfheal_tick` 触发前检查：30 分钟（可配置）窗口内重启次数 ≥3 次（可配置）→ 进入冷却
- 冷却自**首次进入时刻锁存** `cooldown_duration_seconds`（默认 600）；锁存期内即使窗口计数
  因条目老化回落到阈值之下，仍保持冷却状态（否则「冷却持续 10 分钟」不成立）

### FR-2: 冷却状态行为
- 冷却期间 `_maybe_stale_selfheal_tick` 跳过触发，原因标记为 `cooldown`，并清零 idle 计时
- 冷却持续 10 分钟（可配置），期间记录 INFO 日志（状态边沿一次，不逐 tick 刷屏）
- 冷却首次进入（边沿）升级为 admin 告警：经 `admin_store.append` 落 `signal_type:
  stale_selfheal_cooldown`，`severity: warning`；MUST NOT 复用 `stale_code` 类型——该类型写入即
  自动 `mark_handled`，复用会被当已处置吞掉

### FR-3: 自触发型 stale 识别与升级
- 重启后 5 分钟（可配置）内若再次检测到 stale，视为 self-triggered
- self-triggered stale 仅记录 WARNING 日志，不写 restart_request
- 计数以「**重启周期**」为单位（同一进程内多次 tick 只计一次）并持久化到 restart_history.jsonl
  的 `self_triggered_streak`：距上次重启 ≥ 自触发窗口的过期重启使 streak 归零，自触发窗口内的
  重启使 streak +1。只放进程内存则阈值恒不可达（每次自触发都伴随一次重启、新进程归零）
- streak 达到 3 次（可配置）后升级为 admin 告警：经 `admin_store.append` 落 `signal_type:
  stale_selfheal_loop`，`severity: critical`

### FR-4: _is_idle 补全
- 在 `_is_idle` 中增加对 `agent_runner._running_agents` 的检查，读法
  `getattr(getattr(self, "agent_runner", None), "_running_agents", None) or {}`
- 若任一 run 在飞则返回 False；缺属性 / None 视为该维度为空，MUST NOT 抛异常
  （`_is_idle` 已有「异常按非空闲」策略，抛异常会把缺属性态误判为非空闲）
- 依据：spec-review 评审 run 不占 `pm_engine._active_runs`（`core/pm_engine/dispatch/queue.py:44-48`
  `_active_reviews` 独立登记，评审条目「不占 _active_runs/_active_priorities」），故既有空闲判定
  对在飞评审 run 不可见——重启会在评审中途杀掉它

## 接口设计

配置字段（stale_code_selfheal config 下，均在 `ConfigLoader.get_stale_code_selfheal_config`
（`core/config.py:1167`）白名单返回内）：
- `cooldown_window_seconds`: 滑动窗口时长，默认 1800（30 分钟），非正整数回退缺省
- `cooldown_threshold`: 窗口内重启次数阈值，默认 3，非正整数回退缺省
- `cooldown_duration_seconds`: 冷却锁存时长，默认 600（10 分钟），非正整数回退缺省
- `self_triggered_window_seconds`: 自触发检测窗口，默认 300（5 分钟），非正整数回退缺省
- `self_triggered_threshold`: 自触发升级阈值，默认 3，非正整数回退缺省

校验沿用既有范式：bool 陷阱显式排除（`isinstance(True, int)` 为真）、非法值回退缺省、不抛异常。
配置暴露面：五键经 `.fenix/config.yaml` 文件配置 + 30s 热更新生效；本 SPEC 不扩展 Dashboard 面板
与 `/api/config` 写白名单（该节为键级白名单合并，面板保存既写不进新键也不会清除文件侧新键）。

## 行为规范

- 配置 `enabled: false` 时所有冷却机制不生效（向后兼容）；冷却无独立开关，非正整数回退缺省
  （`0` 不等效关闭冷却）
- restart_history.jsonl 超过 24 小时的条目自动清理；文件缺失 / 行损坏按空处理，不阻断自愈
- 冷却期间陈旧告警仍保持显示（仅跳过触发重启）
- 既有 `tests/test_stale_code_selfheal.py` 的 `_DaemonParts` 未设置 `agent_runner` 属性，`_is_idle`
  读取须容忍缺属性；`test_both_sources_empty_is_idle` / `test_idle_threshold_triggers_write`
  等既有用例不得回归
