# 概览页窄宽度适配：统计卡数字行换行 + 台账横向滚动下限下调（2026-11-16）

## 背景

用户需求（2026-11-16）：小宽度下 overview 页卡片需要换行（如 Token 消耗卡「245.5万 平均每 SPEC …」曾 nowrap 溢出卡缘截断）；项目清单台账的「项目」列最大宽度要缩小一些，避免横向滚动条。已直接实现（不走 SPEC），本文为知识候选兼改动归属自证，供 distill 车道折叠。

## 结论（当前事实）

- **改动文件（共 2 个，未提交）**：`core/dashboard/static/src/pages/overview/components/IntroduceRow.tsx`、`core/dashboard/static/src/pages/overview/components/ProjectTable.tsx`。全局样式零改动（`.overview-tile-numrow` 的 <768px 媒体查询规则原样保留，与此番 inline 化的通用 wrap 行为同向不冲突）。
- **TokenTile 数字行换行**：numrow 撤销 `whiteSpace: 'nowrap'` 改 `flexWrap: 'wrap'`（gap 竖向 4px 横向 8px）；「平均每 SPEC X」注释 span 自带 nowrap 保证作为整体参与换行不在词中断开。宽卡内容放得下时不触发换行——宽视口观感零变化（layout-first 手法，非宽度微调）。
- **ActiveAgentTile 数字行换行**：撤销 `whiteSpace: 'nowrap'` + `overflow: 'hidden'` 裁剪承载（图例此前窄卡被硬剪），改 `flexWrap: 'wrap'`；类型图例 inline-flex span 同开 `flexWrap: 'wrap'` 兜底类型极多场景。
- **台账横向滚动下限**：`scroll={{ x: 1060 }}` → `890`。固定列宽合计 604（SPEC数 96 + 任务进度 220 + 问题/阻塞 108 + 活跃运行 108 + 操作 72），无宽度的「项目」列最小宽由 1060−604=456px 收窄至 286px（名称/胶囊行可换行、12px mono 路径约 170px 放得下）。容器 ≥890px 时表格仍按 100% 铺满、项目列吃剩余空间——宽视口列宽分配不变。
- **窄宽度边界口径**：实测 994px 视口 sider 收起态容器 898px ≥890 → 无横向滚动条；sider 展开态容器仅 706px 仍有滚动条（低于表格最小宽，属 <768px 视口移动堆叠卡形态的接管区间，本番不扩移动断点）。
- **JSX 属性注释形态**：Table JSX 开标签内注释须用 `//` 行注释形态（文件既有惯例）；`{/* */}` 表达式容器在属性位非法，esbuild 报 `Expected "..." but found "}"` 构建失败。

## 证据

- `npm run build`：exit 0（umi max 编译含 TS 转译）。
- `npm test`：481/481 pass。
- playwright 几何证据（127.0.1:8787 实站）：994px 收起态 `.ov-bento-table .ant-table-content` clientWidth=scrollWidth=898（无横向滚动条）、首列 294px；numrow 三卡 computed flexWrap=wrap、scrollWidth≤clientWidth 无截断；1600px 宽视口首列 900px、卡片全单行（PC 零影响）；700px 移动档 2×2 网格（332px 列轨）与 wrap 规则完好。截图存 `.history/overview-994-collapsed.png`、`.history/overview-1600.png`。

## 更新目标页（distill 时）

- `spec/knowledge/domains/dashboard-frontend/dashboard-overview.md`（台账磁贴条目补 scroll.x=890 横向滚动下限口径：构成 604+项目列最小 286、容器 ≥890 铺满不变、994px sider 收起态恰好容纳）。
- `spec/knowledge/domains/mobile-adaptation/mobile-overview-density.md`（「数字注释不截断」规则作用域由 <768px 扩至窄宽度桌面：数字行 nowrap/overflow:hidden 裁剪承载退役，wrap 为通用承载、宽视口不触发即零影响）。

## 二轮增量：台账列宽视口双档（2026-11-16 同日用户追加指令）

- **需求**：「表格只压缩名称列」不够——页面缩小时大部分空间从项目列出，其余各列也应适当贡献一点。
- **定案手法：视口断点 JS 双档，非纯 % 列宽**。纯 % 会让宽视口列同步变宽/项目列变窄，违背 dashboard 域「PC 零影响」文化；antd Table 固定布局下 px 列宽不随容器收缩，故唯一既保宽档原值、又让窄档让位的手段是按视口换一组列宽。断点取 antd xl=1200（`useMediaQuery('(max-width: 1199.98px)')`，通用钩子新立 `src/hooks/useMediaQuery.ts`，与 useIsMobile 同款首帧同步模式）。
- **双档数值**（`LEDGER_WIDTHS` 常量，ProjectTable.tsx）：宽档 96/220/108/108/72（合计 604）+ `scroll.x=890`；窄档 80/190/92/92/56（合计 510，让位 94px）+ `scroll.x=700`（=510+项目列最小 190）。列宽下限须按表头/内容实宽核算（如「问题/阻塞」头 ≈78px ≤92），不能拍脑袋。
- **实测边界**（sider 展开态容器）：1200 视口容器 912 走宽档无滚动条；1199 走窄档；994 视口展开态容器 706 → 表 706、项目列 196，无滚动条（一轮时该态仍有滚动条，此番彻底消除）；1600 宽档列宽与原值逐像素一致。守卫 `tests/overviewLedgerNarrowColumns.test.mjs`（源码扫描习语）。
- **教训**：横向滚动条治理做到「消除」而非「减轻」的钥匙是 scroll.x 下限 + 固定列让位双管齐下；只调 scroll.x 时固定列不收缩，容器更窄处必复发。
