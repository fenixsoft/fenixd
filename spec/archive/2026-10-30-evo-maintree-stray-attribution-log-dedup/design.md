# design：maintree-stray-attribution-log-dedup

## 落点

- core/worktree_manager/stray_wip.py：MainTreeStrayWipSweeper。

## 状态设计

__init__（246-277 行既有三个 first_seen 注册表旁）新增：

- self._last_session_attr = None：上次留痕键，取（tuple(sorted(files)),
  占用者会话标识）——文件集按路径排序，对齐 _fingerprint（547 行）「路径
  排序集」惯例，防调用方顺序抖动击穿去重。会话标识取 info.holders 首项
  session 字典的 identity 字段（mergeback.py 会话 clue 构造处同名，
  types.py describe() 渲染「会话=」同源；stray_wip.py:480 的 session 变量
  即该字典），取不到时用空串占位。
- self._attr_suppress_count = 0：自上次留痕起被抑制的轮数。
- self._attr_last_log_ts = 0.0：上次留痕时间戳（time.time() 单调比较）。

## 分支改造（_tracked_sweep_locked 473-492 行）

1. 现有 pop / _reset_registry_absent 行为保持不变（计时与复位语义不动，只动日志维度）。
2. 计算 key = (tuple(files), session_id)：
   - key 与上次不同：落全量行（沿用现文案），更新 key、计数清零、ts=now。
   - key 相同且 now - ts >= 3600：落聚合行「近 1h 重复归因 N 次，归因未变: <files>」，计数清零、ts=now。
   - 其余：计数加一，不落日志。
3. 解除路径（单点判定，MUST NOT 依赖归因分支被执行）：占用者整体清空时
   session_attributed=False（463 行 info.holder 为假），473 行归因分支根本
   不进入、key 比较不发生——「表现为 key 变化」仅对 holders 仍在场但
   identity 取不到的子情形成立。故解除判定挂在归因分支之前：本轮
   _last_session_attr 非空且（not session_attributed 或 files 为空）即补一条
   「会话归因解除」行并清 _last_session_attr、抑制计数清零；覆盖文件消失
   （432 行 clean 分支）、占用者清空、归因迁至在飞车道三类迁移。宽限升级
   处置接管必先经「归因消失轮」（会话归因散件每轮被 pop/复位、不入
   first_seen 注册表，478-479 行，自身永不升级），解除行在归因消失轮即落，
   升级是其后无主流内的事，无需单挂。解除后同会话再归因 key 与解除前同值
   ——因 _last_session_attr 已清，判「与上次不同」自然按首次落全量行
   （R3 闭环，防解除后再归因被抑制计数吞掉）。

## 边界与取舍

- 重启丢状态：仅损失重启后首轮一条重复留痕，与 tracked 流 first_seen 内存态（stray_wip.py:34-45 D5 决策）同一哲学。
- 不持久化到 AdminStore：模块注释明令不新增 signal_type，进程内去重是合规落点。
- 多文件并存（如 todo.md 与 build 日志同时在册）：文件集本身是 key 的一部分，集合变化自然触发新留痕，无需特殊处理。
- 与既有 major 告警一次性标记（516 行 escalated_at）正交，该维度不动。