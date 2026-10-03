# 验证报告：upgrade-narrative-to-investigation

> ⚠️ 本报告由框架于 2026-10-03T17:48:01Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-03T17:48:01.170637+00:00+run-result@mtime1791049681210119148

## 结论：✅ 通过（verified）

**状态：verified — 15/15 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 15/15 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 7.94M |
| 本链增量 Token（输出） | 0.11M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| narrative-pending-placeholder-banner | 「调查生成中」占位渲染：带 narrative_pending:true（侧车未就绪）的未处理裁决告警在 overview 横幅显示「调查生成中」占位，机械字段（描述/证据）照常可见、不出现四段叙事内容、裁决下拉不被遮挡。（出处：spec/changes/upgrade-narrative-to-investigation/tasks.md 3.5；core/dashboard/static/src/components/alert-shared.tsx:77-148 AlertNarrative/AlertLines 渲染单源；core/dashboard/static/src/pages/overview/components/AlertBanner.tsx:153/201-212 横幅与裁决下拉；core/dashboard/static/src/app.tsx:123 /overview 路由） | pass | 0/6 | - |
| narrative-pending-absent-legacy-alert | 回归：无 narrative 且无 narrative_pending 的存量形态告警不渲染「调查生成中」占位、不渲染叙事区块（无空壳），横幅与证据照常，裁决下拉可交互——占位仅在数据层显式附 narrative_pending 时出现。（出处：core/dashboard/static/src/components/alert-shared.tsx:131 narrative 纯条件渲染；core/dashboard/static/src/pages/overview/components/AlertBanner.tsx:153；tasks.md 3.3 narrative_pending 仅未 handled 且侧车缺失时附加） | pass | 0/6 | - |
| narrative-four-section-banner-render | 四段叙事（异步补叙合并后）在横幅完整渲染：「发生了什么/调查结论/为什么需要你决策/决策选项」四段标题依次可见，含「AI 生成」标注，证据文本共存，裁决下拉不被遮挡——既有 AlertNarrative 对四段 Markdown 兼容。（出处：spec/changes/upgrade-narrative-to-investigation/tasks.md 3.5 四段 Markdown 兼容确认；core/dashboard/static/src/components/alert-shared.tsx:77-100；core/dashboard/static/src/app.tsx:123） | pass | 0/8 | - |
| alerts-endpoint-shape-regression | GET /api/alerts 端点契约回归：200 且响应含 alerts/resolved 数组与 total_unhandled 整数——异步补叙改造后读侧合并仅增字段，告警端点响应骨架不回归。（出处：core/dashboard/routes/alert_routes.py:63-134 _api_alerts 响应形状；core/dashboard/routes/base.py:552 路由注册） | pass | 0/2 | - |
| alert-handled-unknown-project-404 | 处置闭环不受异步化影响的负路径回归：POST /api/alerts/<id>/handled 项目判定双分支契约——未注册项目名（project_by_name 返回 None）返回 400 unknown project；404「资源不存在」保留给已注册但目录缺失（与 _api_alert_resolve 同条件统一）。（出处：core/dashboard/routes/alert_routes.py _api_alert_handled 双分支；core/dashboard/http_server.py:122 project_by_name；契约由 dc5e1147 引入早于本 spec，写路径 _error 直写契约不变） | pass | 0/2 | - |
| unit-tests-narrative-upgrade-pass | 本 spec 扩展交付的单元测试 tests/test_adjudication_narrative.py 全绿：四段结构校验（含缺段/旧三段失败走兜底）、采集器三态注入（齐备/部分缺失/非 verify 族）、16K 截断段界保留、facts 注入与缺省跳过、熔断器（3 连败跳过/成功复位/enabled=false 旁路）、超时 180 与 2 次尝试。（出处：spec/changes/upgrade-narrative-to-investigation/tasks.md 5.1 交付物） | pass | 0/2 | - |
| unit-tests-narrative-sidecar-pass | 本 spec 新建交付的单元测试 tests/test_narrative_sidecar.py 全绿（假通道不真调网关）：告警先落盘后补叙（发射耗时不含 LLM 时延）、侧车原子写与读侧合并字段形态、handled 后照常补叙、侧车缺失 pending 标记、清理级联删除。（出处：spec/changes/upgrade-narrative-to-investigation/tasks.md 5.2 交付物） | pass | 0/3 | - |
| four-section-structure-contract | 进程内直驱 core.adjudication_narrative 结构契约：REQUIRED_SECTIONS 四段逐字固定（发生了什么/调查结论/为什么需要你决策/决策选项）；_validate_structure 四段齐全且顺序不倒置才通过，旧三段/缺调查结论/倒置一律判失败；build_narrative 四段输出落 text/model 字段、旧三段输出返回 None 走兜底；超预算四段输出截断后整体 ≤8192 且四标题保留、各段仍有内容、顺序不倒置。（出处：tasks.md 2.1/2.2；core/adjudication_narrative.py:51/390/409/438 既有单源锚点） | pass | 0/11 | - |
| evidence-collector-injection | 证据采集器行为契约（假通道捕获 prompt）：验证族信号（judge_rerun_cap）在四产物齐备时 prompt 注入【验证材料】段且含验证报告正文与失败场景标识；材料缺失/部分缺失降级不阻断（fail-open，机械字段照常注入）；非 verify 族信号（spec-review-rejected）跳过材料段；超长报告按 16K 级预算分段截断且其他材料段不被挤掉（段界保留）。（出处：spec/changes/upgrade-narrative-to-investigation/specs/narrative-investigation-upgrade/spec.md「按 signal_type 的证据采集」；tasks.md 1.1） | pass | 0/12 | - |
| sidecar-async-nonblocking-retry | 异步补叙行为契约（假通道直驱 attach_narrative，不真调网关）：通道慢（2.5s）时 attach 立即返回（<1.5s，落盘路径零阻塞）且 entry 不被同步写入 narrative；数十秒内侧车 .fenix/admin_alerts_narrative/<alert_id>.json 出现且含 alert_id/text/model/at 四字段与四段文本；首次失败重试一次成功；两次全败至多 2 次调用后放弃、不出现侧车（不重试风暴）。（出处：tasks.md 3.1/3.2；core/adjudication_narrative.py:494 attach 既有锚点；core/pm_engine/family.py:1101-1103 发射点） | pass | 0/9 | - |
| circuit-breaker-trip-skip | 连续失败熔断行为契约：通道恒败时连续告警逐条生成（每条至多 2 次尝试），第 3 条告警起生成被跳过（计数不再增长——第 4 条零 LLM 调用），失败留痕 WARNING 出现，失败告警不产生侧车。（出处：spec/changes/upgrade-narrative-to-investigation/spec.md「连续失败熔断」场景「网关事故期熔断止血」；tasks.md 4.1） | pass | 0/7 | - |
| narrative-disabled-bypass | narrative_enabled=false 时熔断器与生成整体旁路：注入禁用配置后 attach 零 LLM 调用、零侧车、立即返回（行为与功能落地前一致）。（出处：spec/changes/upgrade-narrative-to-investigation/spec.md「admin.narrative_enabled=false 时熔断器旁路（整体关闭优先）」；tasks.md 4.1） | pass | 0/4 | - |
| sidecar-merge-read-side | 读侧合并契约（进程内装配临时项目）：get_alerts 按 alert_id 合并侧车 narrative 字段（text/model/at 形态不变）；侧车缺失的未 handled 告警附 narrative_pending=true 且无 narrative；已 handled 无侧车不附 pending；已 handled 有侧车照常合并（历史完整性）；admin_alerts.json 本体保持不可变（侧车承载补叙、本体无 narrative 字段）。（出处：tasks.md 3.3/3.2；core/dashboard/data/admin_alerts.py:10-14 get_alerts 读侧单源；core/dashboard/routes/alert_routes.py:106 路由消费点） | pass | 0/7 | - |
| cleanup-cascade-sidecar | 告警清理级联删除侧车（进程内装配）：AdminStore 保留上限裁剪（MAX_RECORDS=150）移出最旧记录时，其侧车文件同步删除；未裁剪记录的侧车保留；新记录照常入册。（出处：tasks.md 3.4；core/admin_store.py:43-56/241-284 MAX_RECORDS 与 _mutate 裁剪路径） | pass | 0/5 | - |
| wiring-config-docs-dist | 接线/配置/文档/构建产物源码级契约：三个发射点仍共享 attach_narrative 单源（不内联第二套生成逻辑）且预留可选 facts 参数位；DEFAULT_TIMEOUT_SECONDS 与 ConfigLoader 缺省、config.template.yaml 三键同步 180/true；帮助文档更新（调查结论段/侧车补叙/熔断/narrative_timeout_seconds）；dist 构建产物含 narrative_pending 前端新代码；两个测试交付文件在位。（出处：tasks.md 1.2/3.2/交付物清单；core/pm_engine/family.py:1049/1101；core/config.py:1588-1601/1650-1655；docs/help/06-governance.md:277-293） | pass | 0/16 | - |
