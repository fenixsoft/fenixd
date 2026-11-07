# 移动端 UI 修正（1107）

## 背景

2026-11-07 用户在移动设备上提出五处适配修正指令；全部按 mobile-adaptation
域既有约束落地（<768px 条件分支承载、PC 端零影响、改布局不做宽度微调）。

## 结论（当前生效规则）

1. **SPEC 列表移动端内容区背景 = 白底**：theme.ts `SPEC_LIST_MOBILE_BG`
   单源值由 `#e3e3e3` 改 `#ffffff`（2026-11-06 原型批注指定的灰底偏离色
   退役）。白磁贴卡靠发丝边分界，不再靠灰底衬托。DESIGN.md 一般域条款与
   add-spec-list-mobile-style design.md 偏离声明已同步改白（偏离色登记随值
   退役；改值走附则修正案程序的纪律不变）。
2. **测试回归页签概览三按钮移动端纵排**：RegressionTab `overviewActions`
   纯渲染单元新增 `mobile?: boolean` 形态——<768 时 `<Space direction="vertical">`
   + 三键 `block` 全宽（同页筛选 Drawer 页脚 block 按钮习语），span Tooltip
   承载层转 block；桌面缺省横排右对齐逐字节不变。现产 projects/detail 与
   v2/projectDetail 共用本组件，两侧同时生效。
3. **配置页标题栏作用域控件移动端瘦身**：现产 settings/index.tsx 标题栏
   filters 槽位「作用域：」标签移动端不渲染，Select 宽度移动档 130（对齐
   v2/settings.tsx 移动档同值）、桌面 200 不变——顶栏窄幅下标签+宽下拉会把
   标题行挤到换行。
4. **指挥中心双过滤下拉移动端落标题栏下方**：command-center/index.tsx 双
   Select 声明收单源（projectSelect/orgWinSelect 元素常量，isMobile 只切
   宽度承载），移动端不注册 PageTitleBar filters 槽位（`filters={undefined}`），
   改落内容区首行 flex 行（项目 Select flex:1 铺行宽 + 时间窗定宽 100，
   时间窗仅组织总览显示的既有条件显隐不变）；桌面 filters 槽位顶栏右上角
   原样零改动。
5. **帮助页「文档目录」按钮移动端迁标题栏右侧**：现产 help/index.tsx 移动
   分支按钮由内容区首行迁 PageTitleBar filters 槽位（standalone 落顶栏
   右上角 FiltersSlot 天然右对齐、embed 行壳位 FiltersNode marginLeft:auto
   落行右端），内容区只剩正文卡片；桌面分支（左侧目录列形态）零改动。
   移动端 filters 槽位放按钮的定式与 v2/help.tsx 同构（该页 mobile 分支
   早已如此声明）——**filters 槽位即移动端「标题栏右侧控件位」的单一定点**，
   控件上移标题栏的需求一律走此处，不再在内容区手画按钮行。

## 证据

- `npx tsc --noEmit` 改动前后错误总量一致（63 行，全存量）；前端 node 测试
  410 全过（含 regressionTab.test.mjs overviewActions 桌面锚、helpPageScroll
  桌面滚动结构锚）。
- umi `npm run build` 后 390×844 视口实测（.history/mobile-fix-*.png）：
  spec-mobile-content 背景 rgb(255,255,255)；回归三键纵向全宽堆叠；配置页
  顶栏「配置」+ 窄下拉一行排布无换行；指挥中心顶栏无下拉、首行「全部项目+
  今日」横排，1280 桌面视口双下拉仍在顶栏右上角原位；帮助页顶栏「帮助 +
  文档目录」按钮靠右、正文卡片上移首行，点按钮目录抽屉正常滑出。
