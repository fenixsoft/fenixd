# design：maintree-stray-attribution-log-dedup

## 落点

- core/worktree_manager/stray_wip.py：MainTreeStrayWipSweeper。

## 状态设计

__init__（259-285 行既有三个 first_seen 注册表旁）新增：

- self._last_session_attr = None：上次留痕键，取（files 元组, 占用者会话标识）。会话标识来自 info.holders 首项的 session 字段（与现 483 行 join 的来源一致），取不到时用空串占位。
- self._attr_suppress_count = 0：自上次留痕起被抑制的轮数。
- self._attr_last_log_ts = 0.0：上次留痕时间戳（time.time() 单调比较）。

## 分支改造（_tracked_sweep_locked 473-487 行）

1. 现有 pop / _reset_registry_absent 行为保持不变（计时与复位语义不动，只动日志维度）。
2. 计算 key = (tuple(files), session_id)：
   - key 与上次不同：落全量行（沿用现文案），更新 key、计数清零、ts=now。
   - key 相同且 now - ts >= 3600：落聚合行「近 1h 重复归因 N 次，归因未变: <files>」，计数清零、ts=now。
   - 其余：计数加一，不落日志。
3. 解除路径：文件消失/升级处置走既有 _reset_registry_absent 与宽限流的位置，若 _last_session_attr 覆盖相关文件则补一条「会话归因解除」行并清 _last_session_attr；占用者清空在归因分支自然表现为 key 变化。

## 边界与取舍

- 重启丢状态：仅损失重启后首轮一条重复留痕，与 tracked 流 first_seen 内存态（stray_wip.py:34-45 D5 决策）同一哲学。
- 不持久化到 AdminStore：模块注释明令不新增 signal_type，进程内去重是合规落点。
- 多文件并存（如 todo.md 与 build 日志同时在册）：文件集本身是 key 的一部分，集合变化自然触发新留痕，无需特殊处理。
- 与既有 major 告警一次性标记（516 行 escalated_at）正交，该维度不动。