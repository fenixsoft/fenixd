## Deliverables

```yaml
- path: core/dashboard/static/src/pages/activities/index.tsx
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: modify
```

## 1. 视图重组：取消项目页签，全局 Radio 切换

- [x] 1.1 删除项目 Tabs（「全部」+ 项目页签 + 条数 Badge）及 activeKey 状态与项目消失回退 effect，页面改为单一内容区
- [x] 1.2 viewModes（per-project Record）简化为单一 viewMode state（默认 'auto'），「自动运维 / 人工告警」Radio 全局一份置于页面头部
- [x] 1.3 项目数据展平合并：`projects[].activities` 合并为全局单数组，`handled === false` 置顶优先、组内按 `created` 倒序（design D2），每条卡片保留项目 Tag

## 2. 运维事件 Timeline 分页

- [x] 2.1 新增 `PAGE_SIZE = 15` 常量，antd Pagination 外挂 Timeline（design D2）：默认渲染最新 15 条，翻页 slice 渲染对应批次
- [x] 2.2 SSE 刷新重拉数据后保持当前页码；新数据总页数小于当前页时回退第 1 页（design D5）
- [x] 2.3 空数据展示「暂无运维记录」空态（合并后为空即空态，不再有分组空态）

## 3. 人工告警全局化

- [x] 3.1 AlertPanel 去掉 project 过滤谓词，全部项目的未处理/已解决告警合并渲染，每条标明所属项目
- [x] 3.2 「已解决」Collapse 改 `defaultActiveKey={['resolved']}` 默认展开（design D4），保留手动收起能力
- [x] 3.3 「标记已处理」乐观更新 + 后端确认语义回归（跨项目任一条目可标记）

## 4. 构建产物与验证

- [ ] 4.1 重建 v3 前端产物（npm build）并将 `core/dashboard/static/dist/` 提交入库（design D6）
- [ ] 4.2 按声明式验证契约跑 dashboard UI 验证（verify.yaml prepare/serve/ready + BASE_URL；勿打主树 :8787 常驻实例），覆盖 spec 全部 Scenario：默认 15 条/翻页/置顶/空态/已解决默认展开/告警合并/标记已处理
- [ ] 4.3 回归确认不受影响：overview 横幅告警、SpecDocModal 内 admin-invoke-dialog（getAdminActivities 带 project+spec 过滤）、AdminRunModal「查看处置过程」
