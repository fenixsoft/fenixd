# Design: Stale Selfheal 重启冷却机制

## 架构设计

在现有 `_maybe_stale_selfheal_tick`（`fenixd.py:1001-1090`）流程中，在「检查 restart_request 是否存在（in-flight）」与「检查 _is_idle」之间插入冷却检查。

### 数据流

```
_maybe_stale_selfheal_tick 每秒调用
  │
  ├─ _code_stale == False → 清零恢复（现有逻辑不变）
  ├─ 阻断原因判定 → in-flight/disabled/unmanaged（现有逻辑不变）
  ├─ [NEW] 读 restart_history.jsonl → 窗口内重启数 ≥ 阈值？或冷却锁存未到期？
  │     └─ 是 → reason = "cooldown"，清零 idle 计时，边沿落一条冷却告警
  ├─ _is_idle() [修改：增加 _running_agents 检查]
  ├─ 累计空闲时长 ≥ confirm_seconds
  │     ├─ [NEW] 距最近一次重启 < self_triggered_window_seconds → self-triggered：
  │     │       仅记 WARNING、不写 restart_request，并把本重启周期标记为自触发；
  │     │       周期收尾重启时按持久化规则更新 self_triggered_streak，达阈值升 critical 告警
  │     └─ 正常触发 → 写 restart_request + 追加 restart_history.jsonl（含 streak）
```

### 持久化

`.fenix/restart_history.jsonl`：每行一个 JSON 对象，append-only

- `{"ts": "ISO8601", "self_triggered": bool, "self_triggered_streak": int}`
- 写入时机：成功写入 restart_request 后追加（同一成功路径，写失败仅记日志不阻断重启）
- 清理时机：`_maybe_stale_selfheal_tick` 入口处清理超过 24 小时的条目
- 容错：文件不存在 / 行损坏 / 字段缺失按「该条忽略」处理，不抛异常、不阻断自愈

### 冷却语义（`cooldown_duration_seconds` 的消费点）

两个条件**任一**成立即 `reason = "cooldown"`：

1. **窗口计数**：`[now - cooldown_window_seconds, now]` 内重启条数 ≥ `cooldown_threshold`；
2. **冷却锁存**：`now - self._cooldown_started_at < cooldown_duration_seconds`（`self._cooldown_started_at`
   为首次因条件 1 进入冷却的那个 tick 时刻，进程内状态）。

锁存是「冷却持续 10 分钟」这一文档承诺的落地点：只有窗口计数会因条目老化提前退出冷却，
锁存确保冷却期满前不再触发。冷却告警按**边沿**落一次（`_cooldown_started_at` 由 `None`
变为时刻时），不随 1s tick 重复堆积。

### self-triggered 计数语义（阈值可达性）

「连续 self-triggered 次数」以**重启周期**为计数单位（同一进程内多次 tick 只计一次），并把
`self_triggered_streak` 持久化到 restart_history.jsonl，跨进程重启累计：

- 距上次重启 ≥ `self_triggered_window_seconds` 的**过期重启** → streak 归零（循环已断）；
- 处于自触发窗口内的重启 → streak = 上一条记录的 streak + 1。

计数只放进程内存则阈值恒不可达：自触发窗口（300s）短于每次自触发的后果——窗口一过仍陈旧且
空闲即重启，进程换新后内存计数归零，单进程最多形成 1 次自触发。持久化是 `self_triggered_threshold`
可达的必要条件。

### 关键决策

1. **冷却检查位置**：在 in-flight 阻断之后、_is_idle 之前——避免影响正常的首次触发流程
2. **self-triggered 检测**：比较最近一次重启时间与当前时间差——若 < self_triggered_window 则标记
3. **向后兼容**：冷却**无独立开关**，整体关闭走 `stale_code_selfheal.enabled: false`；五个新增
   整数字段沿用既有 loader 范式（`core/config.py:1167-1194`）回退缺省——非正整数回退缺省，
   `0` **不等效关闭**（与 `idle_confirm_seconds` 一致，见 `tests/test_stale_code_selfheal.py`
   的 bool 陷阱 / 0 回退用例）
4. **_is_idle 读法**：`getattr(getattr(self, "agent_runner", None), "_running_agents", None) or {}`
   （与 `fenixd.py:1712` / `fenixd.py:1865` 同款）。裸对象 / CLI 态缺 `agent_runner` 属性时该维度
   视为空——直接 `self.agent_runner...` 会抛 AttributeError，而 `_is_idle` 的「宁紧勿松」策略
   会把它吞成「非空闲」，使既有用例（`tests/test_stale_code_selfheal.py::_DaemonParts` 未设置该
   属性）失真
5. **告警 signal_type**：冷却用 `stale_selfheal_cooldown`（severity: warning）、自触发升级用
   `stale_selfheal_loop`（severity: critical），经 `admin_store.append({...})` 写入（字段结构同
   `fenixd.py:944-970` 的 stale_code 告警）。MUST NOT 复用 `stale_code`——该告警写入即
   `mark_handled`（`fenixd.py:969-970`），复用会被当已处置吞掉
6. **配置暴露面**：五个新键经 `.fenix/config.yaml` 文件配置，30s 热更新生效。本 SPEC 不改
   Dashboard 面板与 `/api/config` 写白名单：`dashboard_data.write_config`
   （`core/dashboard/data/config_admin.py:1023-1031`）对该节做**键级白名单合并**并保留非受管键，
   面板 payload 仅提交 `enabled` / `idle_confirm_seconds`——既写不进新键，也不会清除文件侧新键

### 文件变更清单

- `fenixd.py`（仓库根）：修改 `_is_idle`（增加 _running_agents 检查）和 `_maybe_stale_selfheal_tick`（增加冷却逻辑）
- `core/config.py`：增加 stale_code_selfheal 配置字段的解析与默认值
- `tests/test_stale_selfheal_cooldown.py`：覆盖冷却触发、自触发识别、_is_idle 补全
- `docs/help/07-safeguards.md`：空闲判定口径补 `_running_agents` 维度、补冷却与自触发告警语义
- `docs/help/09-config.md`：`stale_code_selfheal` 键表与 yaml 样例补五个新键
