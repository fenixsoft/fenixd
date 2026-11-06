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
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 组件堆叠形态

- [ ] 1.1 `PageTitleBar` 新增声明式堆叠（如 `subtitleBelow` 布尔，命名实现期定）：声明页 SubtitleNode 从标题行内移出、渲染为标题行下独立行（12px tertiary、左对齐标题首字）；缺省 false 行内形态不变；两壳位（行壳位/顶栏槽）与 embed 档同构支持；移动端 `!isMobile` 零改动。

## 2. 两详情页切换声明

- [ ] 2.1 v1 `projects/detail.tsx` PageTitleBar 声明堆叠（中文标题移到标题行下方）。
- [ ] 2.2 v2 `v2/specDetail.tsx` PageTitleBar 声明堆叠（「中文标题 · branch」组合随之移到下方，branch 空只显中文标题、title 空维持 branch 单独显示、双空不渲染的既有组合规则不变）。
- [ ] 2.3 同步面盘点与回校：浏览器实测两详情页新栏高，盘点命中标题栏高度的页内偏移常数（56/60、126/130 同族字面量中与两页相关者）并回校；未命中常数不动；页签/内容区无遮挡错位（桌面 + 窄屏各验一次）。

## 3. 测试与收尾

- [ ] 3.1 守卫测试同步：`specTitleSubtitle.test.mjs` 断言改堆叠形态（下方独立行/左对齐；未声明页行内形态不变补一条）；`pageTitleBar.test.mjs` 钉死堆叠声明形态与缺省行内形态；pageChrome/embedMount 既有测试全过（偏移若回校则同步新值）。
- [ ] 3.2 前端测试套件全过 + 生产 rebuild（`dist/index.html` 锚点刷新）；本地起服务对两详情页截图取证（副标题下方堆叠、行内未声明面不变、窄屏不渲染）存 `.history/`。
