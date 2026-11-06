## Deliverables

```yaml
- path: core/dashboard/static/src/components/PageTitleBar.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: core/dashboard/static/src/pages/v2/specDetail.tsx
  kind: modify
- path: core/dashboard/static/tests/specTitleSubtitle.test.mjs
  kind: modify
- path: core/dashboard/static/tests/pageTitleBar.test.mjs
  kind: modify
- path: core/dashboard/static/tests/embedMount.test.mjs
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

> 主体代码与守卫测试已随 5e085bb0c / 6d7ead201 落地（fast-track 事后成文留痕）；下方已勾选项为落地确认，剩余项为收尾。

## 1. 详情页富标题内部下方行（已落地，确认）

- [x] 1.1 v1 `projects/detail.tsx`：中文标题作为块级第二行收进 richTitle 富标题内部（12px tertiary、单行省略、贴排 lineHeight 14px、width:0/minWidth:100% 定宽不推开右簇）；四处 PageTitleBar 声明零 subtitle 槽；title 缺失不渲染；移动端 gate。（5e085bb0c/6d7ead201）
- [x] 1.2 v2 `v2/specDetail.tsx`：中文标题 · branch 组合经单源 combineSpecSubtitle 收进 richTitle 富标题内部下方行（branch 空只显中文标题、title 空维持 branch 单独显示、双空不渲染）；零 subtitle 槽；移动端 gate。（5e085bb0c）

## 2. 两列结构与移动端（已落地，确认）

- [x] 2.1 richTitle 两列结构：左列（英文名+中文下方行）、右簇（模式/状态 Tag/胶囊 + 快速切换下拉/状态转移）分列，外层 alignItems center 右簇随标题块整体取中；窄视口 wrap 右簇下坠。（6d7ead201）
- [x] 2.2 移动端只显标题：右簇与中文下方行均 !isMobile/!mobile gate 不渲染。（6d7ead201）
- [x] 2.3 偏移常数盘点：两详情页实测未命中 56/60、126/130 同族字面量，既有常数未动；页签/内容区无遮挡错位。

## 3. 测试与收尾

- [x] 3.1 守卫测试同步：`specTitleSubtitle.test.mjs` 钉死零 subtitle 槽 + 富节点内部下方行断言（v1/v2 各一条 + combineSpecSubtitle 四分支）；`pageTitleBar.test.mjs`、`embedMount.test.mjs` 富标题适配同步。（5e085bb0c）
- [x] 3.2 前端测试套件全过（406 pass / 0 fail）+ 生产 rebuild（`dist/index.html` 锚点刷新：umi.38c20375.js → umi.9e79c2a6.js）；本地起服务（worktree 实例 ：18911）playwright-cli 对两详情页截图取证（桌面下方堆叠 12px/14px 贴排+width 0/minWidth 100%、两列 clusterCY=leftCY=28 居中、390px 移动端只显英文标题、零 subtitle 槽、概览页行内形态不变）存 `.history/`，DOM 事实与截图副本归档主树 `.fenix/verify-evidence/add-titlebar-subtitle-stacked/`。
