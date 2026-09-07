## Deliverables

```yaml
- path: core/dashboard/static/src/global.less
  kind: modify
- path: core/dashboard/static/src/app.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/pages/overview/components/ProjectCards.tsx
  kind: modify
- path: core/dashboard/static/src/pages/activities/index.tsx
  kind: modify
```

## 1. 触控目标工具类与四处落地

- [x] 1.1 global.less 尾部追加 `.touch-expand` 工具类（移动端作用域）：`display:inline-block; padding:8px; margin:-8px`
- [x] 1.2 四处落地：list.tsx SpecCardList「更多」Button、ProjectCards.tsx「进入」「更多」Button、detail.tsx「文档」Typography.Link、activities/index.tsx「查看处置过程」Button（处理其内联 `padding:0,height:'auto'` 冲突）

## 2. SPEC 列表进度单一表达

- [x] 2.1 list.tsx SpecCardList 进度行右侧：`progress >= 100 ? '已完成' : \`${progress}%\``（仅移动端卡片分支，桌面表格列不动）

## 3. detail 顶部压缩

- [x] 3.1 app.tsx HeaderCrumb 的 Breadcrumb 加 `global-header-crumb` className；global.less 追加移动端作用域 `display:none`
- [x] 3.2 detail.tsx headerCfg title 的 Space 加 `wrap`

## 4. 运维记录渐进披露

- [x] 4.1 activities/index.tsx：ActivitiesPage 持 `useIsMobile()` 经 ActivityTimeline 下传 ActivityCard（各加 isMobile prop）
- [x] 4.2 ActivityCard 手写折叠：`isMobile && summary.length > 300` 时 summary 容器 `maxHeight:88 + overflow:hidden + 渐隐 mask`，尾部「展开全文/收起」按钮（`touch-expand`）；失败原因/处置/建议区块不折叠
- [x] 4.3 Timeline items 补 `key={a.id}`

## 5. 构建与双视口验证

- [x] 5.1 `cd core/dashboard/static && npm run build` 构建通过
- [ ] 5.2 playwright 390×844：「更多/进入/文档/查看处置过程」命中区 ≥32px 且视觉无变形；已完成 SPEC 卡显示「已完成」；详情页顶栏无面包屑、Tag 行不溢出；长摘要卡默认折叠、「展开全文/收起」往返正常、安全信息可见、SSE 推送后展开态不串卡；全程 `scrollWidth <= 390`
- [ ] 5.3 playwright 1920×1080 对照基线：顶栏面包屑可见、四处链接现状不变、SPEC 表格进度列双表达、运维记录全文展开无按钮，逐像素一致

## 验证修复（第 1 轮失败）

- [ ] 先复核失败有效性：逐条核对 `spec/changes/fix-mobile-touch-disclosure/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [ ] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [ ] 修复后重跑验证确认通过
