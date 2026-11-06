## Deliverables

```yaml
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/theme.ts
  kind: modify
- path: core/dashboard/static/tests/specTitleSubtitle.test.mjs
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
- path: DESIGN.md
  kind: modify
```

## 1. 移动卡片重绘（UI 真相源对齐）

- [x] 1.1 重读 `specs/dashboard-spec-table/prototype/index.html` 定稿原型与 `prototype/mobile-390-full.png` 截图凭证，对照 DESIGN.md 红线（静态渲染零动画、字号阶、tabular-nums、配色单源）（注明：png 截图本环境禁止读取，以 proposal 指定 UI 真相源 index.html 355 行全文逐区块对照替代，红线四项逐项过检）
- [x] 1.2 重绘 `SpecCardList` 卡片结构：白磁贴（12px/发丝边）内发丝线分卡；卡=英文名主行（14px/600 单行省略）+中文标题次行（12px 三阶灰单行省略，title 缺失不渲染）+语义胶囊行（状态 tone 色对软底 999 带色点、等待标记灰软底、模式 快速橙/标准灰）+⋮ 更多（32px 触控，菜单含 查看文档/调整优先级/冻结 既有项）
- [x] 1.3 阶段进度区：阶段名+「计数 · 百分比」同行在条上方（phaseProgressOf 单源共用桌面列）、进度条阶段 ramp 色（progressPhase 单源，禁另写色表）；终态卡省略进度区；草稿/无计数显「—」不显 0
- [x] 1.4 元信息行（优先级|创建时间|耗时，tabular-nums 12px 竖线分隔）+run 活跃「● 运行中」（success 静态）+验证行（✓/⚠）+信息行（amber 软底摘要单行省略）
- [x] 1.5 fix-* 子卡缩进 26px+`└` 前缀灰符（buildTree 树形单源不变）；整卡点击进详情（specDetailPath 单源）

## 2. 移动筛选编排

- [x] 2.1 状态筛选改横向滚动 chips（全部/各状态+计数徽标，激活黑底白字），替换现产状态多选控件在移动端的呈现；搜索框与 specKeywordHit 命中语义零改动
- [x] 2.2 新增「筛选」底部 Drawer（antd Segmented：类型 全部/开发/fix-*、归档 未归档/已归档、排序 名称/优先级/进度/创建时间；「查看结果」关闭生效），类型/归档过滤语义与现产一致（注明：任务行「类型 全部/开发/fix-*」与尾句「过滤语义与现产一致」矛盾，按约束句裁决——Segmented 承载现产 ListTypeFilter 语义（''=全部/active=进行中/completed=已完成）配现产标签 全部/进行中/已完成，原型「开发/fix-*」为假数据表述不落码；specKeywordHit/归档语义零改动）
- [x] 2.3 分页改磁贴底部「加载更多」block 按钮+「共 N 条 · 已显示 M 条」caption（数据层 pageSize 20 语义不变）
- [x] 2.4 内容区背景色 theme.ts 新增 #E3E3E3 单源常量并在本页内容区消费；DESIGN.md 修正案登记该色值条款（偏离收口，见 design.md 偏离声明段）
- [ ] 2.5 顶栏/桌面分支零改动自证：≥768px 视口列表渲染 diff 前后一致（桌面表格列/整行点击/树形/信息子行现状）

## 3. 守卫与验证

- [ ] 3.1 `specTitleSubtitle.test.mjs` 移动卡锚点改钉新卡结构（英文名主行/中文标题次行/胶囊行/缩进└），桌面列锚不动；`node --test tests/*.test.mjs` 全绿
- [ ] 3.2 `npm run build` 成功；390px 视口实拍列表页与原型逐区块对照（卡片层级/胶囊/进度/元信息/信息行/筛选 Drawer/加载更多），截图存 `.history/`
