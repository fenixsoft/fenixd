# request: redesign-command-center-ledger

指挥中心「执行台账」页签移动端形态（2026-11-07 fenix-prototype 确认环）。

## 界面原型（UI 真相源）

- `prototype/index.html` — PC 端（对齐现产 pages/command-center/ExecutionLedger.tsx，用户指令 PC 端不改）
- `prototype/m-ledger.html` — 移动端 390px（现产无移动分支，本稿定设计）
- 渲染凭证：`prototype/screenshots/`（index.png / m-ledger.png）

## 定稿状态

- vendor 层（react 19.2.7 + antd 6.6.0 真组件，具约束力）
- 2026-11-07 用户批注一轮即定稿（批注：KPI 2×2 网格中间横竖分隔线去掉，
  已应用后冻结）；「不用下一轮确认了，定稿。修改执行台账页面的移动样式。」
- 锚集：cc-topbar / cc-filter-select / cc-kpi-bar / cc-kpi-{delivered,
  intervention,success,cost} / cc-gateway-badge / cc-ledger-table（PC）；
  cc-m-topbar / cc-m-filter-select / cc-m-tabs / cc-m-kpi-grid /
  cc-m-kpi-{delivered,intervention,success,cost} / cc-m-gateway-badge /
  cc-m-ledger-rows / cc-m-ledger-row-{1,2,3}（移动）
- 布局要点（移动）：过滤行内容首行（现产既有编排）；KPI 单磁贴 2×2 无内
  分隔线 + 网关徽标跨列行；台账九列转直接行三行结构（SPEC+结果色字 /
  项目·车道·trigger / 耗时·tokens·成本·时间），发丝线分隔、无卡壳、不分页；
  左右边距 16px。主题 theme.ts DSH_* 一般域单源。
