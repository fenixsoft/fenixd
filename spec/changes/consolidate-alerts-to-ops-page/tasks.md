# Tasks: consolidate-alerts-to-ops-page

```yaml
# Deliverables — 实现分支必须落位的交付物（kind: new/modify/delete 为硬校验，reference 仅审计）
- path: core/dashboard/static/src/hooks/useOpsAlertBadge.ts
  kind: new
- path: tests/test_alert_background_dispatch.py
  kind: new
- path: spec/changes/consolidate-alerts-to-ops-page/verification-report.md
  kind: new
- path: core/dashboard/static/src/pages/overview/components/AlertBanner.tsx
  kind: delete
- path: core/adjudication_narrative.py
  kind: delete
- path: tests/test_adjudication_narrative.py
  kind: delete
- path: core/dashboard/static/src/pages/overview/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/activities/index.tsx
  kind: modify
- path: core/dashboard/static/src/app.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/components/alert-shared.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/SystemPanel.tsx
  kind: modify
- path: core/pm_engine/family.py
  kind: modify
- path: core/pm_engine/mergeback.py
  kind: modify
- path: core/pm_engine/token_budget.py
  kind: modify
- path: core/dashboard/data/admin_alerts.py
  kind: modify
- path: core/dashboard/data/command_center.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/config.py
  kind: modify
- path: tests/test_narrative_sidecar.py
  kind: modify
- path: docs/help/09-config.md
  kind: modify
- path: docs/help/06-governance.md
  kind: modify
- path: .fenix/config.template.yaml
  kind: reference   # gitignored 运行时模板，:447-464 叙事段由人工在主树清理（记入 verification-report.md）
```

## 1. 叙事生成链退役（写侧）

- [ ] 1.1 迁移让位判定：将 `narrative_yielded_to_arbiter`（`core/adjudication_narrative.py:79-101`，三条件链头派发判定：链头派发可用/非黑名单/project_root 可解析）语义逐字迁至 `core/escalation_chain.py`（或 family.py 就近，函数名去 narrative 前缀）；`core/pm_engine/family.py:1950-1975` 消费点改引新位置；判定异常分支由「回落 narrative 路径」改为零后台派发（仅 WARNING 日志）。
- [ ] 1.2 拆除 schedule_narrative 派发：family.py 告警写盘路径移除叙事 attach/后台补叙线程与 narrative_* 配置读取；ArbiterLane `submit_for_alert` 车道与队列满直派回落（报告经 narrative 槽位原位写入）保持不变。
- [ ] 1.3 拆除旁路发射：`core/pm_engine/mergeback.py` 与 `core/pm_engine/token_budget.py`（:507 直写 AdminStore 处）移除叙事 attach 调用，告警发射与人工队列语义不变。
- [ ] 1.4 删除 `core/adjudication_narrative.py`；`core/config.py` 同步移除三键定义与 `DEFAULT_TIMEOUT_SECONDS` 模块内 import（:2520，回退值 180 就地内联），消除模块引用。

## 2. 配置面收缩

- [ ] 2.1 `core/config.py` + `core/dashboard/data/config_admin.py`：narrative_enabled/narrative_timeout_seconds/narrative_model 三键自默认值、校验与设置 schema 暴露中移除；补测试断言存量用户 config 携带 narrative_* 键时 loader 容忍（未知键忽略）不报错。
- [ ] 2.2 `docs/help/09-config.md` 移除三键文档段；`.fenix/config.template.yaml:447-464` 叙事注释段为 gitignored 运行时文件（SPEC 不可交付），将该人工清理项记入 verification-report.md。

## 3. 读侧合并保留与收件箱定形

- [ ] 3.1 `core/dashboard/data/admin_alerts.py`：保留侧车报告读侧合并与告警清理级联删除；移除 narrative_pending 派生及输出。
- [ ] 3.2 `core/dashboard/data/command_center.py` aggregate_inbox：响应定形移除 narrative_pending 字段；narrative 仅当告警已合并历史侧车或 arbiter 报告时携带。
- [ ] 3.3 前端字段与占位退役：`services/dashboard.ts` 移除 narrative_pending 字段（AlertItem :548/:575 与收件箱卡 :1746 相关引用）；`components/alert-shared.tsx` 删除 AlertNarrativePending 组件及渲染分支；hasNarrativeReport/AlertReportButton/narrative 正文渲染保留（服务历史侧车与 arbiter 报告）。
- [ ] 3.4 测试改造：`tests/test_narrative_sidecar.py` 移除生成类用例（TestAlertFirstNarrativeLater 等）、保留读侧合并/级联删除/原子写；删除 `tests/test_adjudication_narrative.py`；新建 `tests/test_alert_background_dispatch.py` 覆盖：迁移后让位判定语义、不让位与判定异常时零后台派发零 LLM 调用、旁路发射点零 attach、新告警无 narrative 字段无新侧车。

## 4. 概览告警面退役与运维徽标

- [ ] 4.1 新建 `core/dashboard/static/src/hooks/useOpsAlertBadge.ts`：复用 services/dashboard 的 STREAM_URL 与 getAlerts；SSE alerts/admin_activities 事件合帧 500ms + 永久断连降级 30s 轮询 + visibilitychange 门控（恢复可见补拉）+ 卸载清理；计数口径 count = alerts.filter(a => Array.isArray(a.choices) && a.choices.length > 0).length。
- [ ] 4.2 `app.tsx` 运维菜单项（:159）name 包 antd Badge（size small，>99 显示 99+）；embed=1 无菜单时 hook 不挂载。
- [ ] 4.3 删除 `overview/components/AlertBanner.tsx`；`overview/index.tsx` 摘除 `<AlertBanner refreshTick>`（:226）与全部告警管线（SSE 告警订阅、合帧句柄、降级轮询定时器与标记），getOverview 30s 心跳与可见性门控保留；守卫断言概览页无 getAlerts/clearAllAlerts 残留引用。
- [ ] 4.4 `SystemPanel.tsx` 移除叙事三键控件；ArbiterPanel 的叙事报告展示不动。

## 5. 清理入口迁移与回归验证

- [ ] 5.1 `activities/index.tsx`：桌面 AlertPanel 顶部操作栏（根因筛选右侧，danger 按钮）与移动端 MobileAlertPane 工具行新增「清理所有事件」；modal.confirm 文案逐字沿用横幅现文案（全部项目 N 条未处理、不可撤销、AdminMonitor 不会对同一告警重新升级、danger 确认键），执行 `clearAllAlerts()` → 成功 message + `load()`；N 取 `total_unhandled`。
- [ ] 5.2 后端相关 pytest 与前端构建全绿；落盘 `spec/changes/consolidate-alerts-to-ops-page/verification-report.md`：徽标计数口径（choices 非空计入、知情类不计）、概览页无告警面、清理入口两形态可用、退役后写告警零 LLM 调用零新侧车、存量 config 残留键容忍、既有告警/裁决/收件箱回归、.fenix/config.template.yaml 人工清理项。
