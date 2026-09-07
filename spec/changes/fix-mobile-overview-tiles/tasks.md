## Deliverables

```yaml
- path: core/dashboard/static/src/pages/overview/components/IntroduceRow.tsx
  kind: modify
- path: core/dashboard/static/src/pages/overview/components/ProjectCards.tsx
  kind: modify
- path: core/dashboard/static/src/global.less
  kind: modify
```

## 1. IntroduceRow 移动端收紧

- [x] 1.1 IntroduceRow.tsx 加 4 处 className：L289 网格容器 `overview-intro-row`、L51 灰眉题 div `overview-tile-eyebrow`、L171 活跃 Agent 数字行与 L238 Token 数字行 `overview-tile-numrow`（L86 任务进度行同加保持一致）
- [x] 1.2 global.less 尾部追加（`:is(.screen-xs,.screen-sm)` 作用域）：统计卡 body `padding: 12px 16px !important`；`.overview-tile-eyebrow { display: none }`；`.overview-tile-numrow { flex-wrap: wrap; white-space: normal !important; overflow: visible !important }`

## 2. 项目清单卡头两行

- [x] 2.1 ProjectCards.tsx L141 Card 加 `overview-project-card` className
- [x] 2.2 global.less 追加：`.overview-project-card .ant-card-head-wrapper { flex-wrap: wrap; row-gap: 4px }`、`.ant-card-extra { flex: 1 1 100%; min-width: 0 }`、extra 内 `.ant-input-search { width: 100% !important }`

## 3. 构建与双视口验证

- [x] 3.1 `cd core/dashboard/static && npm run build` 构建通过
- [x] 3.2 playwright 390×844：四统计卡单标题、body padding 12px 16px、Token「平均每 SPEC」注释完整换行、活跃 Agent 图例完整、搜索框全宽可输入、`scrollWidth === 390`
- [x] 3.3 playwright 1920×1080 对照基线：四卡双标题 + 16px 24px padding + nowrap 单行、项目清单卡头单行 + 160px 搜索框，逐像素一致

## 验证修复（第 1 轮失败）

- [ ] 先复核失败有效性：逐条核对 `spec/changes/fix-mobile-overview-tiles/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [ ] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [ ] 修复后重跑验证确认通过
