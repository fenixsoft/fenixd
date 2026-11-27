## Deliverables

```yaml
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/tests/specNameCopyMenu.test.mjs
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 名称列右键复制菜单

- [x] 1.1 桌面表格名称列单元格（英文名主行 + 中文副标题区域的既有 render 内，`pages/projects/list.tsx`）外包 antd `Dropdown`（`trigger={['contextMenu']}`，弹层经 portal 于行命中面之外），菜单单项 `{ key: 'copy-name', label: '复制 SPEC 名称' }`；归档视图行与 fix-\* 树形子行共用同一名称列 render 天然覆盖，复制内容为该行自身 `record.name`；其他列/表头/空白处不接线（保持浏览器原生右键默认）；移动端卡片流零改动。
- [x] 1.2 「复制 SPEC 名称」点击：在点击同步回调链内 `await copyToClipboard(record.name)`（从 `components/claude-msg/Markdown` 导入既有单源，不在本文件重写 textarea/execCommand 剪贴板实现）；成功 `message.success('已复制 SPEC 名称')`，失败 `message.error`（含原因，不误报成功）；菜单点击后关闭，全程不触发行级导航（portal 隔离即够，不加行级 hack；验证发现 portal 弹层点击沿 React 组件树冒泡命中行 onRow onClick，以 domEvent.stopPropagation 阻断——「不加行级 hack」的意图为零行级 hack，stopPropagation 属菜单级事件阻断，同移动卡 ⋮ 菜单既有习语）；整行点击进详情、名称 Why 悬浮、排序过滤等既有交互代码零改动。

## 2. 测试与验证

- [x] 2.1 新增 `tests/specNameCopyMenu.test.mjs`（node:test 零依赖源码扫描习语，同 specInfoIcon.test.mjs）：钉死——名称列接线 `contextMenu` trigger、单项文案「复制 SPEC 名称」、`copyToClipboard` 导入复用（list.tsx 内 MUST NOT 出现自写 `execCommand`/`createElement('textarea')` 剪贴板代码）、复制键为 `record.name`、移动端卡片分支无 contextMenu 接线。
- [x] 2.2 前端测试套件全过（node --test 全绿）+ 生产 rebuild（`npm run build`，`dist/index.html` 锚点刷新）；本地起服务浏览器冒烟（hash 入口带 `/#/`，rebuild 后 reload）：名称列右键弹菜单且原生菜单被拦、点复制项成功提示且粘贴内容=英文名、Esc/外点关闭、状态列等非名称列右键保持原生默认、右键与复制不进详情、fix-\* 子行与归档行可复制自身名称、整行点击与 Why 悬浮零回归；截图取证存 `.history/`。（fix-\* 子行：live 数据 558 spec 无 children 无法现场出题，以共用单点 render 接线 + 归档视图同本单元格实测覆盖；降级路径按设计文档判据以 node:test 源码扫描钉死 copyToClipboard 复用替代）
