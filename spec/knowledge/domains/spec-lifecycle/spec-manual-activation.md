# SPEC 手工激活（待激活哨兵与激活动作）
<!-- knowledge: capability=spec-manual-activation rev=2
     sources=spec/archive/2026-09-23-add-spec-manual-activation,spec/archive/2026-09-25-fix-scheduling-kick-single-slot -->

`start_after` 哨兵值 `manual` 表示 SPEC 待人工激活：立项/放行入口可把 SPEC 设为待激活，激活动作清除哨兵并即时唤醒派发。

## 规则

- `start_after = "manual"` 语义为「永不到期，须人工激活后方可被调度器拾取」；哨兵为 `StateMachine` 模块级常量 `START_AFTER_MANUAL`，判定大小写不敏感并忽略首尾空白（容错手工编辑 STATE.md）。
- `start_after_pending(entry, now)` 谓词在时间解析**之前**显式判定哨兵：命中即恒返回 True（永远视为未到期），不得落入 `parse_utc` 的 fail-open 分支（该分支对非法值返回「不阻塞」，与哨兵语义相反）；哨兵不被 `parse_utc` 接受为时间；哨兵 SPEC 在所有派发入口（`_on_spec_ready`、dispatch 候选筛选、recovery、admin 巡检）被静默跳过。
- 激活动作 = 将待激活 SPEC 的 `start_after` 置 null，并写入即时唤醒文件信号（载体、写入与失败回报契约见 scheduling-kick-signal 能力），daemon 主循环秒级唤起该 SPEC 的派发，不等 30 分钟周期扫描兜底。
- 「秒级唤醒」以唤醒信号成功写出为前提：写入失败时不得表述为「秒级派发」——接口返回 `ok: true` 并携带「即时唤醒未生效、将由后续扫描派发」的告警字段，SPEC 退回周期扫描兜底。
- 同一时间窗内先后激活两个 SPEC 互不阻塞：两个唤醒信号均成功写入，两者都被即时派发，不出现后者被丢弃。
- 激活幂等且拒绝误操作：对 `start_after` 非 `manual` 的 SPEC（定时值或 null）返回 `ok: false` 附原因且不修改 `start_after`（避免误清定时值）；对不在 STATE.md 的 SPEC 返回未找到；对终态（done/pushed）SPEC 拒绝。
- 设为待激活的入口（仓库内四条）：`/fenix-new` 执行时机确认三选一（立即 / 定时 / 手工激活，经 `add_spec` attrs 写入哨兵）；自进化「同意立项」弹窗三选一（`POST /api/evolution/accept` 接受哨兵值并透传 `accept_item`）；Dashboard「修改状态」弹窗对 ready 态 SPEC 双向操作（待激活时显示「激活（立即调度）」，非待激活时显示「设为待激活」）；CLI `bin/fenix_cli.py activate <spec>` 子命令（非待激活态输出拒绝原因并 exit 1）。
- 仓库外人工步骤：`/fenix-ready` 放行时可一并选择「设为待激活」——该 skill 位于 `~/.claude/skills/` 不属本仓库交付物，改动要点由治理文档（docs/help/06-governance.md）记录、人工在主树同步。
- 待激活 SPEC 与定时拾取、冻结同属「有意等待」族：60s 定时到期检测 `check_scheduling_deadlines` 跳过哨兵 SPEC（不误判「已到期待唤起」）；admin 无待派发巡检与孤儿 ready 恢复将其视为按计划等待——不写 error、不计孤儿、不产生告警。

## 溯源

- [2026-09-23 2026-09-23-add-spec-manual-activation](spec/archive/2026-09-23-add-spec-manual-activation/) — 新增手工激活：哨兵值语义与谓词前置判定、激活动作与误操作拒绝、四条立项/放行入口、到期检测豁免与有意等待不告警
- [2026-09-25 2026-09-25-fix-scheduling-kick-single-slot](spec/archive/2026-09-25-fix-scheduling-kick-single-slot/) — 激活唤醒信号解耦单一文件路径（改经 scheduling-kick-signal 契约）、信号失败如实回报、多 SPEC 先后激活互不丢弃
