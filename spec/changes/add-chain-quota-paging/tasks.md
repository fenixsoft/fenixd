## Deliverables

```yaml
- path: core/dashboard/static/src/pages/activities/components/ChainPanel.tsx
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 前端分页实现

- [ ] 1.1 ChainPanel.tsx「签名配额与上升」段实现客户端分页：每页 10 行、默认第 1 页、页内经 buildQuotaGroups 按 spec 分组渲染；≤10 条不渲染翻页控件，>10 条页脚渲染「上一页 / 第 x / N 页 / 下一页」并做首页/末页禁用与页码钳制；标题徽标总数与 sigIdx 联查保持全量口径不变
- [ ] 1.2 在 core/dashboard/static 跑构建（pnpm build 或等价命令）产出 dist 且无类型/构建错误

## 2. 验证

- [ ] 2.1 跑全量既有测试套件确认零回归（后端未改动），并核对 dist/index.html 构建产物已更新
