<!-- knowledge: capability=blocked-disposition-display rev=1 sources=spec/changes/add-blocked-repairing-display -->

# blocked SPEC 处置相位三态显示

blocked SPEC 在 Dashboard 上的处置相位显示契约：后端从既有处置证据单点判定 agent 自愈相位，前端按相位三态渲染状态标签，让「正在自愈 / 已受理排队 / 等人介入」一眼可分。

## 现行规则

- 判定单点在后端 summary 层：`status=blocked` 的 SPEC 摘要输出 `blocked_phase` 字段（与 `frozen` 同模式——后端单点判定，前端只消费不重复判定），取值 `repairing` / `queued` / `null`。
- `repairing`（存在在飞处置 agent）：`admin-<spec>-` / `arbiter-<spec>-` 前缀 run 处于非终态——agent 归属按 `RUN_ID_AGENT_PREFIXES` 真源表判定（不手写前缀字面量），终态按 run 产物末行映射与元数据 memo 的新鲜度口径；或链状态文件 in_flight 区存在指向该 spec、phase 为 `admin`/`arbiter` 且未超 stale in_flight 超时口径（与 `reap_stale_inflight` 同源 started_at 判据）的条目。
- `queued`（无在飞 run，但 agent 自愈队列挂起该 spec 的待处置件）：只认有持久载体的挂起形态——`admin_alerts.json` 该 spec 的 pending disposition 记录（经 `merge_dispositions_by_run` 归并单点判定「有唤起标记而无 final、待看护重派」，pending 让位于非 pending），或链 in_flight 区 `phase=deferred` 让行条目（同受 stale 超时约束、排除残留）。链派发队列是进程内 `queue.Queue` 无持久落盘，不作判定源。
- `null`（无 agent 处理迹象）：以上皆无，含人工升级件与冻结转人工等待面。升级 kind 告警是「等人」信号，MUST NOT 计入 `queued`——计入会掩护真正需人工介入的件，等人面必须保持「阻塞」以便人工识别。
- 判定优先级 `repairing` > `queued` > `null`；在飞 run 证据取自调用方传入的 run 清单（增量成本近似零），仅 blocked spec 进入告警/链文件持久载体读路径，其余状态零读放大。
- 显示层 only：`blocked_phase` 对 STATE.md 真实状态、调度、列表筛选选项与状态计数零写入零影响，状态计数仍按真实 `blocked` 统计；`STATUS_META` 键域不新增键，真实状态值域不变。
- 前端三态渲染：`status=blocked` 时按相位覆盖状态标签——`repairing`→「修复中」（进行中蓝 info）、`queued`→「排队中」（等待橙 warning）、其余→「阻塞」（critical 红现状）。三态 tone 必须可区分，「修复中」「排队中」不得沿用阻塞的 critical 红；`status != blocked` 的渲染完全不变。
- 渲染单源：`blockedPhaseMeta` 辅助是唯一渲染入口，列表状态列、移动端卡片流、详情页头部与 spec 快速切换下拉共用，禁复制分支；相位元数据键域刻意只含 `repairing`/`queued`，`null`/字段缺席/非法值（存量前端缓存与增量 patch 竞态）统一回退 `statusMeta` 原样（即「阻塞」现状行为），不造第二份阻塞元数据。
- 容错 fail-open：告警/链状态文件缺失、损坏（读层回空骨架/空表）乃至未预期异常一律降级——在飞 run 证据仍可用时按其判定，否则 `null`，绝不沿 `/api/specs` 调用链抛 500。
- 瞬时抖动不做粘滞：处置 run 起飞瞬间 `queued`→`repairing` 的标签跳变在轮询节奏下可接受，无需状态粘滞机制。

## 代码锚点

- core/dashboard/data/summary.py:_blocked_phase — 相位判定单点（在飞 run 半边与 fail-open 兜底）
- core/dashboard/data/summary.py:_blocked_phase_from_persistent_state — 持久载体半边（链在办/让行条目 + 告警挂起件归并）
- core/agent_runner/run_files.py:RUN_ID_AGENT_PREFIXES — 处置 agent 归属前缀真源表
- core/dashboard/static/src/services/dashboard.ts:blockedPhaseMeta — 前端三态渲染单源辅助
- core/dashboard/static/src/pages/projects/list.tsx — 列表状态列与移动卡片流消费点
- core/dashboard/static/src/pages/projects/detail.tsx — 详情页头部与 spec 切换下拉消费点
- 守卫测试：tests/test_dashboard_blocked_phase.py（后端判定口径）、core/dashboard/static/tests/blockedPhase.test.mjs（前端三态渲染）

## 溯源

- 2026-11-09 add-blocked-repairing-display（spec/changes/add-blocked-repairing-display/） — 建立处置相位显示契约：后端 `blocked_phase` 三态判定（数据源全部复用既有单源、升级件不入 queued、显示层零状态机影响）与前端列表/移动卡片/详情页/切换下拉四处三态标签渲染
