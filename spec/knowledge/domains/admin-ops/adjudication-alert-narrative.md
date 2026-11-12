# 转人工裁决告警调查叙事

<!-- knowledge: capability=adjudication-alert-narrative rev=3
     sources=spec/archive/2026-10-06-add-adjudication-alert-narrative,spec/archive/2026-10-09-upgrade-narrative-to-investigation,spec/knowledge/_inbox/done/alert-narrative-generation-chain-retired.md -->

告警记录上的调查叙事槽位：内容只来自历史侧车报告与 Arbiter 车道写入的调查报告，读侧按 alert_id 合并渲染；告警机械字段（description/evidence/recommended_action/choices/trigger）自足支撑裁决，系统对告警零叙事生成调用。

## 规则

- **零生成不变式**：全部告警发射点——汇聚咽喉 `pm_engine._send_human_escalation_alert` 与 mergeback、token_budget 两个旁路点——零后台派发、零 LLM 调用；新告警 MUST NOT 出现 narrative 字段、不产生侧车文件。生成链实现模块 `core/adjudication_narrative.py` 已不存在（任何 import 即 ModuleNotFoundError），按 signal_type 证据采集、四段式生成、连续失败熔断器与重试预算同随生成链俱废，MUST NOT 重建。
- **读侧合并渲染**：narrative 槽位内容仅两类来源——历史侧车（`.fenix/admin_alerts_narrative/<alert_id>.json`，退役前生成）与 Arbiter 车道写入的调查报告（model=arbiter，升级路径原位写入告警记录）；读侧按 alert_id 合并后在 evidence 上方渲染，Markdown、默认展开、带「AI 生成」标注，由「查看调查报告」入口承载。记录无槽位内容时保持无叙事基线渲染：无「调查生成中」占位、无任何 pending 态。叙事是纯可读性增强——choices 下拉与执行按钮交互不依赖叙事，零机器语义。
- **侧车辅助单源**：侧车写/读/删与目录常量单源位于 `core/admin_store.py`（`write_narrative_sidecar`/`load_narrative_sidecars`/`delete_narrative_sidecars`/`SIDECAR_DIRNAME`）；告警清理路径（保留上限裁剪等）级联删除对应侧车防孤儿堆积，按 alert_id 匹配不到的残留侧车忽略即无害；侧车写保持原子写（mkstemp + os.replace）。
- **配置面收缩**：`admin.narrative_enabled`/`admin.narrative_timeout_seconds`/`admin.narrative_model` 三键退役（受管键登记面已无此三键）；存量用户 config 残留的 narrative_* 键按未知键忽略，loader 容忍不报错。
- **让位判定无耦合**：链头派发让位判定（`core/pm_engine/family.py` 的 `yielded_to_arbiter`，路由语义见 [escalation-chain](escalation-chain.md)）与调查叙事槽位无耦合——发射层路由判定不承载任何叙事生成副作用。

## 代码锚点

- 主实现：`core/dashboard/data/admin_alerts.py`（读侧侧车按 alert_id 合并，告警读路径统一并入）
- 单源符号：`core/admin_store.py:load_narrative_sidecars`（侧车读写删与目录常量同文件单源）
- 消费方：`core/dashboard/routes/alert_routes.py`（/api/alerts 聚合读侧出口）；`core/dashboard/data/command_center.py`（裁决收件箱 narrative 字段装配，无 pending 派生字段）
- 守卫测试：`tests/test_alert_background_dispatch.py`（零后台派发契约：判定矩阵/判定异常 fail-open/旁路零 attach/新告警无 narrative 字段无侧车）；`tests/test_narrative_sidecar.py`（读侧合并/级联删除/原子写）

## 溯源

- 2026-10-06 add-adjudication-alert-narrative（spec/archive/2026-10-06-add-adjudication-alert-narrative） — 新增本能力：写入口+旁路点全覆盖接线、三段结构契约与 fail-open 兜底、三配置项与告警区渲染
- 2026-10-09 upgrade-narrative-to-investigation（spec/archive/2026-10-09-upgrade-narrative-to-investigation） — 三段升级为四段并引入按 signal_type 证据采集（16K 预算、fail-open）；同步生成改为机械文案即时落盘 + 侧车异步补叙（超时 180s、至多 2 次尝试）；新增连续失败熔断、终态侧车防悬挂假态、清理级联删除
- 2026-11-12 alert-narrative-generation-chain-retired（spec/knowledge/_inbox/done/alert-narrative-generation-chain-retired.md） — 折叠生成链退役定案（consolidate-alerts-to-ops-page）：零生成不变式与守卫测试入页，规则段收缩为读侧单态（历史侧车+arbiter 报告两源合并渲染）；四段结构/证据采集/熔断器/「调查生成中」占位/narrative_pending 派生/配置三键随退役废除；侧车辅助迁居 admin_store、让位判定迁居 pm_engine/family.py
