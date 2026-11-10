## Deliverables

```yaml
- path: core/dashboard/static/src/pages/activities/components/ChainPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/data/admin_alerts.py
  kind: modify
- path: spec/knowledge/domains/admin-ops/chain-observability.md
  kind: modify
- path: tests/test_dashboard_chain_view.py
  kind: modify
```

> 界面真相源：`specs/redesign-chain-panel-ui/prototype/index.html`（UI 视觉/布局/交互以 prototype/ 为准；本任务清单约束行为与数据语义）。视觉规范基线：bento `.ov-bento` 语言、DSH token（theme.ts）、字号阶 11/12/13/14/16/18/28、数值 tabular-nums、null 显「—」、禁 CSS animation/transition。

## 1. 数据契约与在办富化（后端）

- [x] 1.1 `core/dashboard/data/admin_alerts.py` chain_overview：在办件（in_flight）联查富化——problem 摘要（同签名最近上升件 description 截断，约 160 字符）、admin_attempts_used/admin_cap/arbiter_rulings/arbiter_cap（escalation.chain 或签名配额联查）、run_id 尽力提取（不可得置 null）；联查 fail-open（缺数据字段置 null，不阻断视图）
- [x] 1.2 `core/dashboard/static/src/services/dashboard.ts`：ChainInFlightItem 类型投影扩展（上述富化字段，均允许 null）；不破坏既有调用方
- [x] 1.3 扩展 `tests/test_dashboard_chain_view.py`：在办富化字段单测（problem 摘要截断、admin/arbiter 已用与上限联查、run_id 尽力提取，含联查数据缺失时字段置 null 的 fail-open 分支），既有 summary 与四视图断言保持不变

## 2. 链在办卡

- [x] 2.1 ChainPanel 链在办区行卡重绘：phase 标签（Admin 蓝/Arbiter 紫）+ spec + signal + 已耗时右置 → 问题描述 2 行 clamp → 静态链进度条 Admin n/N→Arbiter n/N→人工（当前阶段强调）→ run/入链时刻/chain_id mono 行；run_id null 显「—」；空态文案（链上无在办件）
- [x] 2.2 在办行点击打开处置过程视图：run_id 可得→复用 AdminRunModal（80vw/72vh 流式转录窗）；否则降级打开该签名最近上升件的详情抽屉（复用 5.2 抽屉）；card-extra 注明可点击

## 3. 签名配额卡

- [x] 3.1 按 spec 分组列表：组头=spec 名+项目标签+last_spec_status+「N 签名·↑M·待 K」，组序按待人工数→上升数→last_seen 降序；废除每行 SPEC 日常标签
- [x] 3.2 签名行 grid：信号名｜Admin/Arbiter 配额双芯片（静态填充条：正常灰 #81858c/顶格橙 #f59e0b/耗尽红 #ec1313）｜链上结果标签（待人工红/已收口绿/顶格橙/无上升件灰字）｜最近出现；granularity≠spec 追加主体键/类型级标签
- [x] 3.3 有上升件的信号名可点击（下钻打开该签名最近上升件的处置过程视图，待人工优先否则最新）；无上升件信号名不可点击

## 4. 人工队列卡（置首）

- [x] 4.1 人工队列卡移至统计行之后、其余三区之前；无待人工件时整卡不渲染（返回 null）；card-extra 标注裁决入口说明
- [x] 4.2 每项内嵌裁决面板：复用 useAlertAdjudication 交互（选择裁决项 Select 含 label/desc、处置依据 Input 可选、执行按钮、标记已处理按钮）接 alert-resolve 闭环端点；destructive 项执行前 Popconfirm 二次确认（「确认执行该裁决？」+desc）；执行成功后队列刷新（该项移除）；面板视觉对齐原型 .adjud-panel 三段式（左标签/中控件列/右动作列）

## 5. 上升件全量卡

- [x] 5.1 行卡替换表格：severity 标签+signal code+spec·项目+终点短标签+状态标签（待人工 volcano/已收口绿）+created 右置 → 描述 2 行 clamp → 链痕芯片行（Admin 已用/上限→Arbiter 已用/上限、裁决选项数、chain_id mono 截断）；分段筛选 全部/待人工/已收口（Radio.Group button 深色激活惯例）含计数
- [x] 5.2 行点击详情抽屉（640px）：描述、证据（pre-wrap 软底）、链痕 Timeline（入链→Admin→handoff→Arbiter→终点 endpoint_reason）、建议处置、裁决选项只读预览（destructive 红描边）+「执行入口收敛于人工队列与告警记录页签」提示；抽屉无执行按钮（只读）

## 6. 统计行与整体回归

- [x] 6.1 5 磁贴统计行：链在办（Admin/Arbiter 分计）、待人工（含 major 分计）、上升件（含近 24h）、签名水位（含 Admin/Arbiter 顶格计数）、签名关联上升（占水位比例·待人工分计）；数值 tabular-nums
- [x] 6.2 页面级回归：bento 视觉核验（磁贴描边/圆角/阴影/字号阶与 `.ov-bento` 一致）、30s 轮询保持（页签失活即卸载停轮询）、项目筛选与 SSE 横幅行为不变、移动端形态不劣化（行卡栅格降级单列）、前端 build+lint 通过

## 7. 知识修订与验证

- [x] 7.1 修订 `spec/knowledge/domains/admin-ops/chain-observability.md`：L16 只读纪律句改为分层只读（人工队列区可裁决=人工裁决主入口；上升件全量列表与详情抽屉只读），L19「处置链视图只读」条款同步改写，L25 来源注释追加本变更条目
- [x] 7.2 端到端验证：dashboard build 通过；curl `http://127.0.0.1:8787/api/chain` 在办件富化字段在位（或显式 null）；处置链页签渲染冒烟（四区行卡、筛选、抽屉、弹窗可用；人工队列空时整卡隐藏）

## 验证修复（原地打回第 1 轮）

- [ ] 先复核失败有效性：逐条核对 `spec/changes/redesign-chain-panel-ui/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [ ] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [ ] 修复后重跑验证确认通过
