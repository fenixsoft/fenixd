# 验证报告：add-adjudication-alert-narrative

> ⚠️ 本报告由框架于 2026-09-29T08:02:16Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-29T08:02:16.253501+00:00+run-result@mtime1790668936281694414

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 6.36M |
| 本链增量 Token（输出） | 0.10M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| alert-narrative-renders-before-evidence | 带 narrative 的裁决告警在 overview 横幅渲染三段式叙事：三段标题「发生了什么/为什么需要你决策/决策选项」依次可见，含「建议倾向仅供参考」标注，证据文本共存可见，裁决下拉不被遮挡。（出处：core/dashboard/static/src/components/alert-shared.tsx:63 AlertLines 渲染单源；core/dashboard/static/src/pages/overview/components/AlertBanner.tsx:125 横幅告警列表与裁决行；core/dashboard/static/src/app.tsx:123 /overview 路由） | pass | 0/7 | - |
| alert-without-narrative-rendering-unchanged | 无 narrative 字段的告警渲染与现状一致：不出现三段叙事内容（无空壳容器），描述/证据照常显示，裁决下拉可交互。（出处：core/dashboard/static/src/components/alert-shared.tsx:63 AlertLines 渲染单源；core/dashboard/static/src/pages/overview/components/AlertBanner.tsx:125 横幅告警列表与裁决行；core/dashboard/static/src/app.tsx:123 /overview 路由） | pass | 0/5 | - |
| alert-narrative-long-text-layout | narrative 文本超过 2000 字符时告警卡片按容器规则折叠/滚动：不横向溢出，choices 操作区（裁决下拉）仍可见可点。（出处：core/dashboard/static/src/components/alert-shared.tsx:63 AlertLines 渲染单源；core/dashboard/static/src/pages/overview/components/AlertBanner.tsx:125 横幅告警列表与裁决行；core/dashboard/static/src/app.tsx:123 /overview 路由） | pass | 0/6 | - |
| alert-banner-empty-state-unchanged | 告警列表为空时横幅整体不渲染（现状行为）：无「需人工介入」横幅、无叙事容器，页面无控制台错误。（出处：core/dashboard/static/src/components/alert-shared.tsx:63 AlertLines 渲染单源；core/dashboard/static/src/pages/overview/components/AlertBanner.tsx:125 横幅告警列表与裁决行；core/dashboard/static/src/app.tsx:123 /overview 路由） | pass | 0/4 | - |
| systempanel-narrative-config-edit-save | 设置页「系统」页签出现叙事三配置控件（narrative_enabled 开关 / narrative_timeout_seconds 数字 / narrative_model 文本），修改超时为 30 并保存后值持久化回显。（出处：core/dashboard/static/src/pages/settings/components/SystemPanel.tsx:322-364 system-field-${key}/system-control-${key} testid 模式；core/dashboard/static/src/pages/settings/index.tsx:426 activeKey==='system' 页签渲染；core/dashboard/static/src/pages/settings/pageLabels.ts:15 页签标签「系统」；core/dashboard/static/src/app.tsx:133 /settings 路由） | pass | 0/7 | - |
| narrative-module-contract-direct | 进程内直驱 core.adjudication_narrative.attach_narrative 模块契约（design D1-D4）：choices 非空且通道正常时写入 narrative{text,model,at} 且三段标题齐全、通道被调用；桶 0（choices 空）零通道调用零 narrative；通道异常不抛出回落机械文案；三段结构缺失回落机械文案。通道经模块注入点注入假通道，不真调网关。（出处：spec/changes/add-adjudication-alert-narrative/design.md D1/D2/D4，tasks 1.1） | pass | 0/8 | - |
| narrative-emitter-wiring-source | 叙事接线与类型源码断言（tasks 2.1/2.2/3.3）：汇聚写入口 pm_engine/family.py 与两旁路点 mergeback.py、token_budget.py 源码均接入同一 attach_narrative（共享模块、无第二套 prompt）；叙事模块内含三段标题 prompt；services/dashboard.ts 告警类型含 narrative 可选字段。（出处：core/pm_engine/family.py:975 汇聚写入口；core/worktree_manager/mergeback.py:476 旁路点一；core/agent_runner/token_budget.py:257 旁路点二；core/dashboard/static/src/services/dashboard.ts:294 AlertItem 类型） | pass | 0/9 | - |
| narrative-config-template-keys | config.template.yaml admin 段新增叙事三键（tasks 3.1）：narrative_enabled/narrative_timeout_seconds/narrative_model 齐备且带中文注释，缺省与 true/60/空一致。（出处：.fenix/config.template.yaml:391 admin 段） | pass | 0/5 | - |
| unit-tests-adjudication-narrative-pass | 新交付单测文件 tests/test_adjudication_narrative.py 全绿（tasks 1.2：三段契约与字段形态、LLM 超时/异常回退、结构校验失败回退、narrative_enabled=false 零调用、桶 0 零调用、模型回退链三档；假通道注入不真调网关）。（出处：spec/changes/add-adjudication-alert-narrative/tasks.md 交付物 tests/test_adjudication_narrative.py） | pass | 0/2 | - |
| governance-doc-narrative-section | 帮助文档补充叙事说明（tasks 5.2）：docs/help/06-governance.md 含 narrative 字段说明（三段结构、生成时机、失败兜底为机械文案）与三个 admin.narrative_* 配置项及设置页入口。（出处：spec/changes/add-adjudication-alert-narrative/tasks.md 交付物 docs/help/06-governance.md） | pass | 0/4 | - |
| dist-build-contains-narrative-code | 前端构建出库验证（tasks 4.2）：core/dashboard/static/dist 构建产物中包含 narrative 渲染新代码（标识符入库），证明 npm 构建已完成且产物含本 spec 前端改动。（出处：spec/changes/add-adjudication-alert-narrative/tasks.md 交付物 core/dashboard/static/dist/index.html reference） | pass | 0/2 | - |
| alerts-endpoint-contract-regression | GET /api/alerts 端点契约回归（api）：200 且响应含 alerts 数组——叙事为纯增强字段，告警端点行为不回归。（出处：core/dashboard/routes/base.py:376 路由注册；core/dashboard/routes/alert_routes.py:43 _api_alerts 响应形状 {alerts, resolved, total_unhandled}） | pass | 0/2 | - |
