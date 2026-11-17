# SPEC 软删除与告警台账一致性

<!-- knowledge: capability=spec-softdelete-alert-linkage rev=2
     sources=spec/changes/add-spec-softdelete-alert-linkage,spec/knowledge/_inbox/done/spec-softdelete-escalation-alert-linkage.md -->

SPEC 软删除事件与告警台账的事件式一致性契约：软删除成功即联动关闭引用该 spec 的全部未处理告警，对已不存在 spec 的丢弃裁决幂等成功——告警条目不因主体消失而悬空成死循环入口。

## 规则

**软删除联动关闭（事件驱动）**

- 联动点在软删除原语 `soft_delete_spec`（SPEC 管理删除端点与裁决 abandon 执行器的共用底层）成功路径内：删除成功即按 spec 名联动关闭 `admin_alerts.json` 中全部未处理且 `spec` 字段等于该 spec 名的告警，kind=escalation 与 kind=signal 同治。两种删除成功形态均联动：目录迁移形态（`archived=True`，目录迁至 `spec/archive/<名>-<Unix秒>/`）与仅清状态形态（`archived=False`，目录本就缺失、仅 STATE 条目迁出）。
- 写回形态：`handled=True`、`handled_by="spec-softdeleted"`（独立署名，与条件族 auto-resolve / 签名自愈 auto-self-heal / 批量失效 superseded 各自独立同范式）、`handled_at` 联动时刻、`resolve_note` 注记删除事实与归档去向——目录迁移形态注记归档目录名（`SPEC <名> 已软删除（归档至 spec/archive/<归档目录名>），关联告警联动关闭`），仅清状态形态如实注记无目录（`SPEC <名> 已软删除（无目录，仅清理状态登记），关联告警联动关闭`）。
- 匹配口径为 `spec` 字段精确匹配，不解析 description 自然语言；`spec` 为空或 `global` 的全局条目经 `is_global_spec` 单源谓词跳过（无具体主体可联动）。
- 保护面：已 handled 条目逐位不动（人工处置记录与既有自动闭环记录不覆盖）；MUST NOT 新增告警条目、MUST NOT 改写 disposition 记录本体；零命中零写回（文件 mtime 不变）；写回在 AdminStore 排他锁内单次读改写。
- fail-open：联动是删除本体的 best-effort 后置步骤，告警写回失败（AdminStore 拒写、IO 异常）不使软删除失败、不回滚目录迁移；`soft_delete_spec` 返回对象如实携带联动结果——关闭条数 `alerts_closed`（零命中为 0），失败说明落独立字段 `alert_link_error` 并 WARNING 留痕。`alert_link_error` MUST NOT 占用返回对象顶层 `error` 键：该键是删除本体的既有失败语义键（abandon 执行器据其判成功分类、删除端点据其报失败），被联动失败占用会把已成功的删除对两个调用方反转成失败。
- 与周期扫描通道的分界：`alert_lifecycle` 条件注册表（见 [告警生命周期自动闭环](alert-lifecycle.md)）按 signal_type 白名单周期扫描，「spec 从状态表消失」不构成任何在册条件的解除证据；本联动是删除事件驱动的独立写回路径，不在扫描通道职责内——spec-review-rejected 等未在册类型经本联动收口，不改动条件注册表与扫描节奏。
- 范围边界：`archive_spec` 归档通道不联动（面向完成态 spec，其告警通常已随终态收口，是否同治属独立产品决策）；手工直接删目录（绕过软删除原语）产生的悬空告警无事件可挂，不经本联动收口。

**对已不存在 spec 的丢弃幂等**

- 裁决执行器 `_exec_abandon` 对 `soft_delete_spec` 返回 `found=False`（活跃 STATE 与归档清单 `.fenix/STATE.archive.md` 双查均无该 spec）判幂等成功而非失败：返回 ok=True、动作步骤注记「spec 已不存在（STATE 与归档清单均无记录），视为已丢弃」，不产生「spec not found」失败结果；该分支无任何目录/STATE 动作发生，不伪造 archived 记账。
- `found=True` 路径行为不变（软删除执行 + 联动关闭告警）；`running`（spec 仍有在跑 agent，拒绝丢弃）与一般 error 分支不变。
- 收口链路闭环：alert-resolve 端点（见 [告警一键裁决处置端点](alert-resolve.md)）对幂等成功结果按既有成功路径标记 handled 并写 disposition 留痕；告警已被联动先行闭环时端点对 marked=False 幂等容忍跳过，处置留痕与 SSE 广播照常。
- 防呆边界：不引入「spec/changes 目录残片仍存在则失败」的第三态判断——目标态达成与否以活跃 STATE + 归档清单双查为准，状态表是唯一真相源，避免第二套真相源。

**归档通道目录命名判别**

- `spec/archive/` 下的归档目录名即通道指纹：`<名>-<Unix秒>/`（无日期前缀）出自软删除通道 `soft_delete_spec`（同步把 STATE 条目或归档清单小节剔除，不向归档清单写入条目）；`YYYY-MM-DD-<名>/`（带日期前缀）出自归档通道 `archive_spec`（SPEC 管理页手工归档与 daemon 自动归档链共用，归档成功即把 STATE 条目迁出至归档清单 `.fenix/STATE.archive.md`，迁出成功附 `state_evicted`、失败降级 `evict_warning` 不回滚目录移动）。排查「spec 已不存在」的悬空告警时，以归档目录名判别当初所走通道，进而判断联动关闭事件是否可能发生过。

## 代码锚点

- 主实现：`core/dashboard/data/spec_archive.py`（`_close_linked_alerts` 联动挂点与返回对象 `alerts_closed` / `alert_link_error` 契约）
- 写回入口：`core/admin_store.py`（`SPEC_SOFT_DELETED_BY` 署名常量、`close_alerts_for_deleted_spec` 排他锁单次读改写）
- 幂等出口：`core/dashboard/data/admin_actions.py`（`_exec_abandon` found=False 分支）
- 守卫测试：`tests/test_spec_softdelete_alert_linkage.py`（联动关闭、幂等丢弃、已处理不动、fail-open 四组场景）

## 溯源

- 2026-11-17 add-spec-softdelete-alert-linkage（spec/changes/add-spec-softdelete-alert-linkage/） — 新建本页：软删除成功联动关闭引用该 spec 的未处理告警（spec-softdeleted 独立署名、fail-open 独立错误字段不占删除本体 error 键）、对已不存在 spec 的 abandon 幂等成功出口
- 2026-11-17 spec-softdelete-escalation-alert-linkage（spec/knowledge/_inbox/done/spec-softdelete-escalation-alert-linkage.md） — 折叠排查候选：补归档通道目录命名判别指纹；条目中「删除不联动关闭告警」「对已软删除 spec 执行 abandon 必败」两条结论已被本页 SPEC 实现规则取代，不再保留
