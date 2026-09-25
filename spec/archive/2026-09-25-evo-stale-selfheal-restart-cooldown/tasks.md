## Deliverables

```yaml
- path: fenixd.py
  kind: modify
- path: core/config.py
  kind: modify
- path: tests/test_stale_selfheal_cooldown.py
  kind: new
- path: docs/help/07-safeguards.md
  kind: modify
- path: docs/help/09-config.md
  kind: modify
```

## 1. 冷却机制实现

- [x] 1.1 core/config.py：在 `get_stale_code_selfheal_config`（core/config.py:1167）的白名单返回中新增 cooldown_window_seconds（默认1800）、cooldown_threshold（默认3）、cooldown_duration_seconds（默认600）、self_triggered_window_seconds（默认300）、self_triggered_threshold（默认3）字段及缺省常量；校验沿用既有范式——bool 陷阱显式排除（`isinstance(True, int)` 为真）、非法/非正整数回退缺省、不抛异常
- [x] 1.2 fenixd.py `_maybe_stale_selfheal_tick`：在 in-flight 检查之后、_is_idle 之前，插入冷却状态检查——读取 .fenix/restart_history.jsonl（容错：文件不存在/行损坏/字段缺失按该条忽略），窗口 `[now-cooldown_window_seconds, now]` 内重启条数 ≥ cooldown_threshold，**或** `now - self._cooldown_started_at < cooldown_duration_seconds`（锁存未到期）→ reason=cooldown、清零 idle 计时；首次进入冷却（`_cooldown_started_at` 由 None 变为时刻的边沿）时经 `admin_store.append` 落一条 `signal_type: stale_selfheal_cooldown`（severity: warning）告警，后续 tick 不重复落
- [x] 1.3 fenixd.py `_maybe_stale_selfheal_tick`：成功触发重启（写入 restart_request）后，追加 `{"ts", "self_triggered", "self_triggered_streak"}` 到 .fenix/restart_history.jsonl（写失败仅记日志，不阻断重启）；每次 tick 入口清理 24 小时前的旧条目
- [x] 1.4 fenixd.py `_maybe_stale_selfheal_tick`：触发重启前检测「自触发型 stale」——若距上次重启 < self_triggered_window_seconds，记 WARNING 日志且不写 restart_request，并把本重启周期标记为自触发；周期收尾重启时按持久化规则更新 streak（窗口内 → 上一条 streak + 1；过期重启 → 归零），streak ≥ self_triggered_threshold 时经 `admin_store.append` 升 `signal_type: stale_selfheal_loop`（severity: critical）告警

## 2. _is_idle 补全

- [x] 2.1 fenixd.py `_is_idle`：在 pm_engine._active_runs 检查之后，增加对 agent_runner._running_agents 的检查——读法 `getattr(getattr(self, "agent_runner", None), "_running_agents", None) or {}`（与 fenixd.py:1712/1865 同款），非空则返回 False；缺属性/None 视为该维度为空，MUST NOT 抛异常（既有 `tests/test_stale_code_selfheal.py::_DaemonParts` 未设置该属性，`_is_idle` 的「异常按非空闲」策略会把 AttributeError 吞成非空闲，使既有用例失真）

## 3. 测试

- [x] 3.1 tests/test_stale_selfheal_cooldown.py：覆盖「窗口内重启 ≥ 阈值触发冷却」「冷却锁存期内即使窗口计数回落仍保持冷却」「自触发型 stale 识别与跨重启 streak 升级（阈值可达）」「_is_idle 含 _running_agents 时返回 False」「缺 agent_runner 属性时不抛异常且判为空闲」场景

## 4. 文档

- [x] 4.1 docs/help/07-safeguards.md：空闲判定口径补 `agent_runner._running_agents` 维度（现文写「planner / implementer / verifier / judge 全部形态均在 `_active_runs` 内」，未含评审 run），并补冷却与自触发告警语义
- [x] 4.2 docs/help/09-config.md：`stale_code_selfheal` 键表与 yaml 样例补五个新键及默认值，说明冷却无独立开关、整体关闭走 `enabled: false`，且五键经配置文件 + 30s 热更新生效（Dashboard 面板未暴露）
