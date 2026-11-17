## Context

2026-11-17 运维页实证（alert `8c715662226d`，详见 `spec/knowledge/_inbox/spec-softdelete-escalation-alert-linkage.md`）：spec `evo-fix-self-review-window-gap` 于 2026-11-16 23:15 经 SPEC 管理删除端点软删除（归档目录 `spec/archive/evo-fix-self-review-window-gap-1794842156/`，提交 `3e18548f3`），其 spec-review-rejected 升级告警（2026-11-16 22:42 发射，推荐 abandon）保持未处理；用户点丢弃 → `_exec_abandon` → `soft_delete_spec` 对 STATE 与归档清单均无记录的目标幂等返回 `{found: False}` → `error="spec not found"` → 端点 400「告警保持未处理，可调整后重试」。告警与 spec 真实状态脱钩：删除通道不联动关告警，告警推荐动作成为死循环入口。

两条软删除通道共用同一底层：
- SPEC 管理删除端点：`core/dashboard/routes/spec_routes.py` ~948 行直接调 `dashboard_data.soft_delete_spec`（→ `core/dashboard/data/spec_archive.py:136` `soft_delete_spec`）。
- 裁决 abandon：`core/dashboard/data/admin_actions.py:2320` `_exec_abandon` 经 `execute_adjudication_choice`（:3147 统一入口）调用同一 `soft_delete_spec`。

既有闭环机制（`spec/knowledge/domains/admin-ops/alert-lifecycle.md`）为周期扫描式：`alert_lifecycle` 条件注册表 `_SIGNAL_CONDITIONS` 按 signal_type 白名单判定，`spec-review-rejected` 不在册（永不自动闭环），且「spec 从状态表消失」不构成任何在册条件的解除证据——事件式联动是缺口所在，不在扫描通道职责内。

## Goals

- 软删除成功即消除悬空告警：删除事件与告警台账在单次操作内一致。
- 存量悬空告警有幂等收口出口（丢弃不再永久失败）。
- 不回归：人工处置记录保护、disposition 台账不可旁路改写、`alert_lifecycle` 扫描通道、choices 注册表、`found=True` 丢弃路径、全局信号（spec 空/global）守卫。

## Decisions

1. **联动点选在 `soft_delete_spec` 内部而非两个调用方各自实现**：删除语义与「主体消失→关联告警失效」是原子因果，双调用方（管理端点/裁决执行器）天然同治，未来新增调用方自动继承。实现上经 AdminStore 既有排他锁写回通道（与 `mark_handled` 同族），按 `spec` 字段精确匹配（空/`global` 跳过，复用 `is_global_spec` 单源谓词），不解析 description 自然语言。
2. **新增独立 `handled_by="spec-softdeleted"` 而非复用 `auto-resolve`**：`auto-resolve` 语义绑定「周期扫描 + 条件注册表 + trigger 字段」，本联动是删除事件驱动、无 trigger 前提；独立取值保证审计可辨（与 `auto-self-heal`/`superseded`/`arbiter` 各自独立取值同范式）。前端 handled_by 徽标渲染对未知取值已有通用兜底，无需前端改动；不新增枚举拦截。
3. **fail-open**：删除本体已发生（目录已迁移），告警写回失败若反向回滚会造成更大的状态分裂；失败如实回报（返回对象字段）留给调用方与人工，不抛异常。与 alert-lifecycle 总则「自动收口只作用于告警条目本身、MUST NOT 改写 disposition 台账」一致。
4. **`found=False` 幂等成功而非维持失败**：`found=False` 在「活跃 STATE + 归档清单」双查后仅意味着「目标态已达成」（spec 不存在），丢弃的意图已满足；维持失败会让悬空告警永久无法经丢弃收口。防呆边界：不引入「spec/changes 目录仍存在则仍失败」的第三态判断（目录残片场景由状态表为准，避免第二套真相源）；`running`（spec 仍有在跑 agent）与一般 error 分支行为不变。
5. **不扩展到 `archive_spec` 通道**：归档通道面向完成态 spec（归档即写归档清单），其告警通常已随终态收口；是否同样联动属独立产品决策，本 SPEC 不做（避免范围蔓延）。
6. **端点层零改动**：`alert_routes.py` 对 `marked=False`（告警已被联动先行闭环）已幂等容忍（code-review item b0a65fc4cf01）；abandon 成功后端点标记 handled 返回 False 幂等跳过，disposition 留痕与 SSE 广播照常。

## Risks

- **联动误伤面**：按 spec 名精确匹配可能关闭「多条不同 signal_type 的告警」——主体消失后这些告警全部失去可处置性，批量关闭正是期望行为；已 handled 条目逐位不动保护人工历史。
- **写回时序**：abandon 经告警执行时联动先闭环告警、端点再 mark（幂等跳过），不产生重复处置；并发面由 AdminStore 排他锁与 alert-resolve per-alert 锁既有语义覆盖。
- **存量数据**：当前在册悬空告警（如 `8c715662226d`）在实现合入后可直接经「丢弃」幂等收口，无需数据迁移。

## Non-goals

- 不改 choices 注册表/选项集、不改 alert_lifecycle 条件注册表与扫描节奏。
- 不为 `handled_by="spec-softdeleted"` 新增前端专属徽标（通用「已解决」渲染即可）。
- 不处理手工直接删目录（绕过 soft_delete_spec）产生的悬空告警（无事件可挂）。
