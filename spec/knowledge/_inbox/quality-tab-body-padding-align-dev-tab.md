# 分面卡体内边距对齐与 facetWrap 移动端校准耦合

## 背景

2026-11-11 用户指令：项目页（`/#/projects/:name`）「代码审查」页签内容区间距
与「功能开发」页签对齐（此前明显过大）。排查发现两分面各自渲染包裹卡，
内边距口径不同源。

## 结论（当前事实）

- 项目页六分面各分面**自带包裹卡**（非共享单卡）。「功能开发」（DevTab，
  `core/dashboard/static/src/pages/projects/list.tsx` 桌面分支）的卡挂
  `projects-page` 类 → `core/dashboard/static/src/global.less`
  `#root .projects-page > .ant-card-body { padding: 8px }`（2026-11-04 收紧档）。
  「代码审查」（QualityTab）等其余分面卡未挂类，吃 antd 缺省 24px——
  同页签容器下两分面卡体左右/顶各差 16px，即「明显过大」的来源。
- 桌面对齐口径：分面包裹卡 body 内边距 **8px**（与 `.projects-page` 档一致）。
  QualityTab 经 antd `styles={{ body: { padding: 8 } }}`（desktop 档）实现。
- **移动端陷阱**：`facetWrap`（list.tsx）对非 dev 分面套 `margin: 0 -20px`，
  该抵消口径按 24px 卡体调校（抵后余 4 + children-container 12 = 每侧 16px，
  2026-11-07 移动边距 16px 指令）。若把分面卡 body 无条件改 8px，移动端每侧
  变 8-20+12=0 → 内容贴穿屏幕缘。**分面卡内边距与 facetWrap 负边距是一对
  耦合参数，改其一必须同步校核另一**；桌面收窄实现 MUST 以 `isMobile` 分档
  （或等价手段）豁免移动端。
- 验证锚点：桌面两分面 contentLeft=279 / contentTop=126（1440 视口）应相等；
  移动端（390 视口）quality 卡 `cardLeft=-8`、`wrapMargin=-20px`、body 24px
  为不变基线。

## 证据

- 改前实测：dev 卡 bodyPad 8px（挂 projects-page），quality 卡 bodyPad 24px。
- 改后实测（rebuild + reload）：quality bodyPad 8px、cardLeft 271；dev 同值；
  移动端三值（24px / -8 / -20px）与改前逐项相等。
- 实现：`core/dashboard/static/src/pages/projects/components/QualityTab.tsx`
  顶层 Card `styles={isMobile ? undefined : { body: { padding: 8 } }}`。
