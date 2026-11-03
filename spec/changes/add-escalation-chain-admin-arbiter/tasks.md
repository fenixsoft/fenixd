## Deliverables

```yaml
- path: core/pm_engine/escalation_chain.py
  kind: new
- path: core/pm_engine/family.py
  kind: modify
- path: core/pm_engine/arbiter.py
  kind: modify
- path: core/pm_engine/budget.py
  kind: modify
- path: core/adjudication_narrative.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/config.py
  kind: modify
- path: agents/administrator.md
  kind: modify
- path: agents/arbiter.md
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/dashboard/data/timeline.py
  kind: modify
- path: core/dashboard/data/admin_alerts.py
  kind: modify
- path: core/dashboard/static/src/pages/chain/index.tsx
  kind: new
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
- path: .fenix/config.template.yaml
  kind: modify
- path: tests/test_escalation_chain.py
  kind: new
- path: tests/test_arbiter_lane.py
  kind: modify
- path: tests/test_timeline_arbiter_visibility.py
  kind: modify
```

## 1. 链入口与派发器

- [ ] 1.1 清点 `_send_human_escalation_alert` 与 `freeze_for_human` 全部调用点并标注来源（框架/链成员），链入口按来源判定：框架信号入链头，链成员产出转单不重入（防自环清单落测试）
- [ ] 1.2 新建 `core/pm_engine/escalation_chain.py`：链级派发器（事件驱动直派、同签名 dedup、复用 Admin 在飞互斥守卫、队列深度上限、黑名单 kill switch 判定、链级失能 fail-open 判定+一次性 WARN）；`core/admin_monitor.py` 兜底看护对象扩展全链在办件（design 决策 1，pending 超时升级语义不变）
- [ ] 1.3 咽喉改道：`core/pm_engine/family.py` 升级边默认调链派发器而非落 admin_alerts；`core/adjudication_narrative.py` 让位判定方向反转（`narrative_yielded_to_arbiter` 从白名单命中让位改为非黑名单即链头派发判定，消费点 family.py:1688）；人工告警写入收敛为链终点专属路径（附链上下文：Admin 尝试痕/台账回链/链 run_id 关联键）
- [ ] 1.4 配额状态文件 `.fenix/escalation_chain_state.json`（daemon 运行时写，代码交付读写层）：签名键（复用 `arbiter_failure_signature` + spec=null 主体键提取）、双车道计数、7 天/状态迁移复位、dead-man 永久单次例外
- [ ] 1.5 新配置键入 `core/config.py`（admin 链配额/复位窗/黑名单清单）+ 单测

## 2. Admin 链上语义

- [ ] 2.1 Admin 尝试配额 2 次/签名（run 崩溃/超时计次，超范围转单不计），耗尽自动转单 Arbiter
- [ ] 2.2 `handoff: arbiter` + `handoff_reason` 结构化产出：AdminDisposition 读侧、`agents/administrator.md` 契约段、`prompt_builder.py` 注入三处同步（不重载 `result=escalate`）；prompt 文件改动先 merge main
- [ ] 2.3 Admin 处置成功框架侧 side-effects：信号收口 + 显式 status 解冻（与 Arbiter `_apply_disposition_side_effects` 同型纪律），并触发链下一动作（如重验证）
- [ ] 2.4 Admin choices 白名单圈定环境运维子集（预算/豁免类不在其拍板面）

## 3. Arbiter 接单与拍板面

- [ ] 3.1 转单载荷注入：Admin 尝试痕（run 摘要/失败原因/handoff_reason）进 Arbiter 调查 prompt（`agents/arbiter.md` 契约段 + prompt_builder）
- [ ] 3.2 预算豁免拍板动作面：Arbiter 处置 side-effects 写 spec 预算 override 字段（复用 `impl_run_budget_override` 等，不新增 schema；`core/pm_engine/budget.py` 消费侧与 `core/state_machine.py` 既有字段先例对齐）+ 台账留痕
- [ ] 3.3 Arbiter 复现配额 2 次/签名：拍板计数、第 3 次复现强制上升；`_dispositioned`/`_ledger_sigs` 单次纪律与回扫排除逻辑改写为配额制（dead-man 例外保留），`test_arbiter_lane.py` 机械守卫同步改写并断言新语义
- [ ] 3.4 失败双轨：自判失败/尝试无效/run 崩溃重试 1/2 次后上升（半成品调查包附上）——沿用既有失败重试骨架接线到上升件路径

## 4. 闭环与迁移

- [ ] 4.1 上升件全链关联键与自动收口：`close_cause` 族新增 `CLOSED_BY_CHAIN`，链上任一级后续成功闭环时收口在队上升件
- [ ] 4.2 存量迁移 daemon 启动 hook（版本哨兵防重跑）：底层已闭环的旧 pending 自动收口（`close_cause=migrated`），不回填入链

## 5. 可见性与配置界面

- [ ] 5.1 时间轴全链节点：Admin 尝试/转单（handoff_reason 摘要）/Arbiter 拍板与复现计数/上升件节点派生（`data/timeline.py`），fail-open；`test_timeline_arbiter_visibility.py` 扩展
- [ ] 5.2 Dashboard 处置链视图：新页 `static/src/pages/chain/index.tsx`（在办/队列/配额水位/上升件；spec=null 按主体键归组；只读），路由与 `data/admin_alerts.py` 单读聚合扩展，构建产物重建（dist 为 reference）
- [ ] 5.3 设置页链配置区块：配额/复位窗/黑名单编辑（`static/src/pages/settings/index.tsx`），30s 热更新生效

## 6. 验收回归

- [ ] 6.1 新建 `tests/test_escalation_chain.py` 覆盖 `escalation-chain` 与 `chain-observability` 全部 Scenario（含设计文档 9 验收场景对应用例）
- [ ] 6.2 降级态逐字节一致测试：kill switch 命中 / `arbiter.enabled=false` / 链级失能三形态下告警路径与合入前一致（对齐「关闭态零侵扰」惯例）
- [ ] 6.3 全量回归：`test_arbiter_lane.py`/`test_admin_store` 族/`test_timeline_arbiter_visibility.py`/dashboard data 层测试全绿
