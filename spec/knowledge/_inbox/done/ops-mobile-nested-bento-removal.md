# 运维页移动端去嵌套 bento（1107 原型重绘批注定稿）

## 背景

v2 运维页（`/v2/activities`，`core/dashboard/static/src/pages/v2/ops.tsx`）移动端
原型重绘确认环（fenix-prototype，draft r2）：旧 `prototype/m-ops.html` 画于
2026-11-05 处置链三页签对齐与 2026-11-06 统一标题栏迁移之前，页签序/命名/顶栏
形态/磁贴圆角全部过时。重绘对齐现产后，用户批注定稿一条移动端呈现规则并确认
「运维页面按此修改」，同轮完成原型覆盖入库（r7eb44fa07）与现产落改。

## 结论（当前生效规则）

1. **v2 运维页移动端形态 UI 真相源 = `spec/changes/redesign-dashboard-v2-ui-mobile/
   prototype/m-ops.html`（2026-11-07 r2 版）**；桌面形态真相源仍是
   redesign-dashboard-v2-ui 的 `prototype/ops.html`。移动端页签：处置链（缺省，
   `?tab=` 仅认 auto/alert 预选）/自动运维记录/告警记录；标题入设备顶栏
   （unified-page-title-bar 移动语义：副标题五项统计与返回箭头移动端不渲染）。
2. **自动运维记录与告警记录两 pane 移动端去嵌套 bento 白卡、直接行呈现**
   （批注原话「移动设备中屏幕宽度有限，不要显示 bento 风格的卡片，直接显示
   内容」，锚 `ops-auto` / `ops-alert-list`）：嵌套白磁贴只在 `<768px` 移动
   分支解除（`mobile` prop 下传 pane），桌面嵌套磁贴形态不变；去卡不改行
   分隔线色档（告警行仍 `V2_SPLIT`、记录行仍 `V2_HAIRLINE`）。通用化表述：
   **v2 页移动端忌「卡中卡」——面板磁贴内嵌套小磁贴的双层边框+双层内边距
   在 390px 视口挤占内容净宽，内容应直接行呈现**（与处置链页签堆叠卡惯例
   同款），可作后续 v2 移动改版的一般候选规则。
3. **共享组件的形态改动以 prop 分支承载、禁止全局平移**：`V2AlertRow` 移动
   分支被运维页与 overview 告警横幅磁贴共用，其 `10px 2px` 行内边距在运维页
   去卡后保留不动（2px 视觉不可辨）——去卡收益来自解除外层磁贴，不在改行距；
   overview 侧零变化。

## 证据

- 原型确认环：draft `.fenix/prototypes/redesign-dashboard-v2-ui-mobile/`（已按
  批准入库流程清理）；批注 `feedback.json` round 1 两条（ops-auto /
  ops-alert-list 同文）；锚保持机械门通过（kept `ops-panel`、`ops-alert-item-1/2/3`，
  受波及换锚 `ops-titlebar`→`ops-topbar`、`ops-chain`→`ops-chain-table`+四段锚）。
- 现产落改：`ops.tsx` ActivityPane/AlertPane 增 `mobile` prop 分支；tsc 改动
  文件零错误；`npm test` 410/410 通过（含 v2TitleBarGuard 守卫）。
- 入库提交：`7eb44fa07`（m-ops.html + screenshots/ops.png 覆盖、design.md
  修订记录、ops.tsx 移动分支）。
- 控制台噪音备忘：vendor.js（react 19.2.7 DEV）对 createElement 多位置
  children 写法恒发一条「数组 key」警告——旧版已入库原型同款，非缺陷信号，
  生产构建不含 DEV React 无此噪音；排查时勿据其返工（本次曾以 createElement
  包裹 / fiber commit 走查 / owner 栈三重探针证伪页面代码后才以旧原型对照实锤）。
