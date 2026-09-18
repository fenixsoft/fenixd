# 实现设计

## 现状

core/admin_monitor.py:1557 _recover_orphaned_dispositions（核心循环）：
1. 分组收集 pending disposition（admin_run_id 维度，1567-1580；`status != "pending"` 即判该 run 为 final）
2. 超时（grace = cooldown ≥ 60m）后：有未处理 escalation → continue（1593）；有 interrupted 标记 → 终结 interrupted（1600-1627）；否则 → escalation + 终结（1628-1660）

core/admin_store.py:502 unhandled_for 只匹配 kind=ESCALATION，不匹配 kind=signal——故孤儿处置无法据它判断底层信号是否已处理。

**字段差异澄清（实测，修正原「ui-manual 信号 spec=None」的说法）**：本仓库 .fenix/admin_alerts.json 现有 50 条 kind=signal 记录，**spec 全部非 None**（spec=None 只出现在 kind=escalation，23 条）；手动唤起路径 core/signals.py:74 写入的请求必带 spec，core/dashboard/routes/spec_routes.py:662 无 spec 直接 404。故「信号 spec=None vs disposition spec=项目名」的字段差异**不存在**：unhandled_signal_for 按 spec 严格相等匹配即可，**不做宽松匹配**（宽松匹配只会扩大误配面，且掩盖真实口径）。

**handled/escalated 口径（实测）**：无任何代码路径对 kind=signal 记录置 handled=true（admin_store.mark_handled 的调用方 self_review / token_budget / family / dashboard / fenixd.py 均只作用于 escalation）。故 `handled=false` 对信号记录近乎恒真，真正的判别项是「该 (spec, signal_type) 是否**已唤起**过」——即 escalated=true：_handle_signal 仅在节流通过、实际唤起时以 escalated=True 落记录（admin_monitor.py:1365-1370），节流分支落 escalated=False（1330-1333）。因此以 escalated=true 作为匹配条件，既对齐 spec.md 的「底层信号」定义，也避免为「从未唤起过的节流沉淀记录」重派。

## 方案

### 底层信号回溯

新增 admin_store.unhandled_signal_for(spec, signal_type)：遍历 read_all()，匹配 kind=SIGNAL ∧ 非 handled ∧ signal_type 相等 ∧ spec 严格相等 ∧ escalated 为真，返回最新一条命中（read_all 已按 created 倒序）；未找到返回 None。与 unhandled_for 同结构、紧随 admin_store.py:502 之后。

### 重派判定（1600 分支前置改造）

已知中断分支处理前，按 (spec, signal_type) 调用 unhandled_signal_for：
- 找到 → 进入重派判定（见下）
- 未找到 → 维持现终结逻辑（1600-1627 原样）

### 重派去重（新增判定，非复用既有）

`_has_active_admin_run_for(spec, signal_type) -> bool`：遍历 store.read_all()，存在 kind=DISPOSITION ∧ signal_type 相等 ∧ spec 相等 ∧ `(status or result) == "pending"` 的记录即为真。

**该辅助方法当前不存在**：admin_monitor.py 全类方法清单（500-2683）中无此名，全仓库 grep `_has_active_admin_run_for` 零命中——必须**新增**，而非「复用既有去重判定」。判据刻意对齐 _recover_orphaned_dispositions 自身的 by_run 口径（1575-1577 同款 `status == "pending"`），不引入第二套「在飞」定义。

### 重派计数

- 读：从 store.read_all() 取同 (spec, signal_type) 的全部 kind=DISPOSITION 记录，取 reschedule_count 字段最大值（缺省 0）。
- 写：每次重派把 reschedule_count = 旧值 + 1 写在**被置为 superseded 的那条新记录**上（store 追加语义，计数由新记录承载，无需原地改写历史记录）。
- 判：旧值 + 1 > MAX_RESCHEDULE（默认 2，模块常量，config `admin.reschedule_max` 可覆盖，非法值回落 2）→ 不再重派，转升级。
  （等价表述：第 1、2 次中断各重派一次；第 3 次中断即升级——与 tasks 3.3 一致）
- 口径说明：计数按 (spec, signal_type) 聚合，跨独立信号事件可能多计；多计方向为**更早升级**（安全侧），与「防无限重派烧钱」的目标同向。

### 重派执行

```
sig_rec = self.store.unhandled_signal_for(spec, sig_type)   # 未找到 → 维持原终结逻辑
signal  = self._rebuild_dispatch_signal(sig_rec)            # admin_monitor.py:2125；None → 维持原终结逻辑
if signal and not self._has_active_admin_run_for(spec, sig_type):
    self._invoke_administrator(signal, sig_rec)
```

_rebuild_dispatch_signal 对 kind=signal 记录走「无 original_signal → 由记录顶层字段 setdefault 补齐」路径即可重建（signal_type/spec/severity/description/recommended_action 均为信号记录顶层字段）。

**不额外写 status=dispatched 的新 disposition**：_invoke_administrator → run_administrator 会自行落 pending 记录（core/agent_runner/maintenance_runs.py:182）并在返回后落最终记录，新 run 的孤儿可检测性由这两条承载。若额外写一条同 admin_run_id 的非 pending 记录，by_run 归并（1570-1580：任一非 pending 即 final=True）会把该 run 永久判为已终结 → 后续中断不再被检测 → 计数永不推进、上限永不生效、信号再次永久悬空（与「重派有界」目标直接矛盾）。

### 审计留痕

- 原 pending disposition：追加 status=superseded 记录（同 admin_run_id = 原 run id），actions_taken 注明 `superseded by rescheduled disposition (signal <sig_id> still unhandled)`，并携带 reschedule_count 新值。追加非 pending 记录即令该 run 被判 final，孤儿循环终止（同 1643-1644 注释所述做法）。
- 升级分支（超限）：沿用 1628-1660 既有实现，escalation（kind=escalation，severity=critical，description 注明中断/重派次数）+ 为该 run 追加 status=escalated 终结记录。
- 「未找到信号」分支：维持 1600-1627 原样（status=interrupted 终结记录）。
- 三个分支都必须为该 run 留下非 pending 终结记录，否则同一孤儿每轮巡检重复升级/重复重派。

## 失败模式

- 重派后再次中断但信号仍未处理 → 计数 +1，直到超限升级（避免无限循环烧钱）
- store 并发写：disposition 追加沿用现 append 语义（append 幂等）
- daemon 在重派 run 在飞时再次停机 → 下一轮孤儿检测重复上述逻辑，幂等
- config `admin.reschedule_max` 非整数/负值 → 回落默认 2（与既有 config 读取容错口径一致）
