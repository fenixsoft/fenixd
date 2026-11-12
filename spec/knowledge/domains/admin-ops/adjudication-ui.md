<!-- knowledge: capability=adjudication-ui rev=3 sources=spec/archive/2026-09-27-add-human-adjudication-choices,spec/knowledge/_inbox/done/alert-narrative-generation-chain-retired.md,spec/changes/consolidate-alerts-to-ops-page -->

# 告警选择题交互

前端对携带裁决选项的告警渲染「下拉选择 + 执行」交互，使人工裁决无需进入 claude code。

## 现行规则

- 带非空 `choices` 的告警在告警卡片内渲染：选项下拉框（`Select`，展示 label+desc）、可选备注输入框（note）、「执行」按钮；裁决承载面为 spec 详情页告警区（`pages/projects/detail.tsx`）、运维页告警记录（移动端行内）与指挥中心收件箱三处，服务层 `services/dashboard.ts` 提供 `resolveAlert` 函数；概览页不承载裁决交互。
- 运维页告警记录的桌面列表行保持既有展示面（条目信息 + 报告入口 +「标记已处理」），无裁决控件也不新增——桌面可裁决面收敛为 spec 详情页与指挥中心收件箱两处。
- 点击执行调用 `POST /api/alert-resolve`：成功 → 该告警转为已处理态并提示处置结果摘要；失败 → 展示错误与已执行步骤说明，告警保持可重试（下拉与按钮恢复可交互，允许改选重试）。
- 执行中按钮处于 loading 态，防重复提交。
- 不带 `choices` 的告警保持既有「知道了」（markAlertHandled）交互，不出现下拉框。
- `abandon`（撤销丢弃）与 `skip_review_gate`（跳过评审门）两类不可逆/降级动作执行前必须二次确认（`Popconfirm` 或 Modal，desc 显示动作后果与 note）；其余动作可直接执行。
- 处置成功提示必须包含「处置留痕已写入 admin 活动记录」，保证人知道裁决已审计。

## 溯源

- 2026-09-27 add-human-adjudication-choices（spec/archive/2026-09-27-add-human-adjudication-choices） — 建立告警选择题交互契约：下拉+执行渲染、三态反馈、知情类无下拉、不可逆动作二次确认与留痕提示
- 2026-11-12 alert-narrative-generation-chain-retired（spec/knowledge/_inbox/done/alert-narrative-generation-chain-retired.md） — 折叠裁决渲染面收缩（consolidate-alerts-to-ops-page）：overview 横幅形态退役，裁决闭环保留于 spec 详情页告警区、运维页告警记录（移动端行内）与指挥中心收件箱三面
- 2026-11-12 consolidate-alerts-to-ops-page（spec/changes/consolidate-alerts-to-ops-page/） — 裁决承载面收缩以 SPEC 定案入库：补运维页桌面行保持现状不增删裁决控件条款（桌面可裁决面=spec 详情页+指挥中心收件箱）
