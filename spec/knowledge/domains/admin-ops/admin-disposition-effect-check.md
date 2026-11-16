# 孤儿处置生效核查代际判定

<!-- knowledge: capability=admin-disposition-effect-check rev=1
     sources=spec/changes/evo-admin-orphan-effect-generation-aware -->

AdminMonitor 对终态处置组的只读生效核查判定：判「处置是否真正达成目标」时识别状态代际更替，处置已生效、其后被新一轮验证合法前移再冻结的 spec 不再误判为处置失效，假告警不进人工面。滞留组补记收敛（backfill）语义见 [admin-orphan-disposition-effect-check](admin-orphan-disposition-effect-check.md)。

## 规则

- 生效核查禁凭 STATE 当前状态快照单源判定：处置组终态后核对 spec 状态，`frozen=True` 不直接判「处置未生效」——须先核查处置组完成时刻之后是否存在指向该 spec 的合法推进轨迹，任一命中即判「已生效、被新代际取代」。
- 代际锚点为处置组完成时刻：处置记录无独立终态时间字段，以组内最新记录的 `created` 为锚（与既有 grace 门 max(created) 口径一致）；轨迹行的日志时间戳必须落在 [锚点, now]，早于锚点的候选行不构成证据。
- 轨迹证据源为状态推进留痕日志家族（fenixd.log 及轮转备份，尾部限量 + mtime 剪枝复用既有读面），匹配契约：`Transition:` 与 `Gate transition:` 两族成功行前缀均认；from→to 属合法迁移（VALID_TRANSITIONS / GATE_TRANSITIONS）；spec 名与本组 spec 精确锚定；channel 不限（auto/manual/recovery 皆认——frozen spec 的自动推进本就被冻结剥离拦截，锚后能出现合法前移必然先有解冻/复位动作，方向安全）。
- 非成功行不构成轨迹：Cannot transition / Invalid transition / Idempotent / Frozen-stripped 等形态不计入。
- 判「被新代际取代」时的消解簿记：旧处置组转记已消解终态留痕（附轨迹证据行引用，不带 escalate=true，不升级人工）；旧组关联 SIGNAL 记录 `mark_signal_handled` 收口；新代际条目以独立于旧组 sig_type 的类型键（`superseded_generation`）落账、携带旧组引用与轨迹证据行、开立即终态/handled 留痕形态——不进未处理人工告警面，不触发人工升级或仲裁调查；冻结态本身的关注由既有解冻调度/监视机制负责。
- 回环抑制靠信号收口自然达成：旧组关联信号收口后，孤儿扫描按未处理信号查询不再命中而跳过本组，不重复转记、不重复开立新代际条目；新代际条目类型键必须独立于旧组 sig_type（复用旧键会每轮重扫描重转记，形成同键回环）。
- fail-closed 边界零变化：无轨迹命中、候选行早于锚点、或日志窗口缺失（轮转丢失）时维持升级人工语义，不因证据缺失放大豁免面。
- 已推进 spec 不入核查分支：STATE 已判「解冻推进」的短路保持前置，轨迹核查只挂在 frozen=True 判 False 分支内，非每轮全量扫描；扫描成本与既有日志家族扫描同量级（尾部限量 + 轮转候选集）。

## 代码锚点

- 判定主实现：`core/admin_monitor.py` `_orphan_group_effect_evidence`（frozen 短路分支内的代际轨迹核查与消解簿记）
- 新代际信号类型键常量：`core/admin_monitor.py` `_ORPHAN_SUPERSEDED_GENERATION_SIGNAL_TYPE`
- 轨迹读面：`core/admin_monitor.py` `_read_recent_unfreeze_transitions`（尾部限量/轮转候选集/mtime 剪枝读面复用，匹配谓词独立定义不逐字复用解冻族谓词）
- 信号收口：`core/admin_store.py` `mark_signal_handled`
- 轨迹留痕源：`core/state_machine.py` 状态推进成功行 INFO 留痕（`Transition:` / `Gate transition:` 两族）

## 溯源

- 2026-11-16 evo-admin-orphan-effect-generation-aware（spec/changes/evo-admin-orphan-effect-generation-aware/） — 新建本页：生效核查代际感知判定（STATE 快照禁单源、组内最新 created 代际锚点、推进轨迹判「被新代际取代」、消解簿记与回链、fail-closed 边界零变化），消解 2026-11-11 web-browser-client 假告警同型误判
