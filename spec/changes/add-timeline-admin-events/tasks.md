## Deliverables

```yaml
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: tests/test_dashboard_data.py
  kind: modify
```

## 1. 后端：时间轴 admin 事件源

- [ ] 1.1 `core/dashboard/data.py` 新增 `_admin_events_for_spec(project_root, spec_name)`：经 `AdminStore.read_all()` 过滤 `kind in {escalation, disposition}` 且 `spec` 字段与目标 SPEC 精确匹配的记录（缺 `spec` 字段跳过），按 `admin_run_id` 归并——组内存在非 pending 最终处置仅保留最新最终处置，否则保留 pending，无 `admin_run_id` 独立保留；输出 `kind="admin"` 节点（`time`=`created`、`record_kind`、`signal_type`、`severity`、`description`、状态字段：escalation 取 `handled`，disposition 取 `result`），读取异常 fail-open 返回空
- [ ] 1.2 `get_spec_timeline` 接入：在 run 节点构建后将 admin 节点并入 `events` 列表（排序与折叠自动生效）；`_timeline_sort_key` kind 次序改为显式映射 state=0、admin=1、run=2，state/run 相对次序不变
- [ ] 1.3 后端回归测试（`tests/test_dashboard_data.py`）：escalation/disposition 节点下发与字段、其他 spec 不串扰、pending 被最终处置替代、仅 pending 独立展示、同秒 state→admin→run 次序、admin 节点打断前向状态折叠、`admin_alerts.json` 缺失/损坏 fail-open、缺 `spec` 字段记录跳过；既有时间轴用例（state/run 次序、折叠）零回归

## 2. 前端：admin 节点渲染分支

- [ ] 2.1 `core/dashboard/static/src/pages/projects/detail.tsx` `renderTimeline` 新增 `kind==="admin"` 分支：标题行 = 时间 + 「运维处置」（disposition）/「升级告警」（escalation）Tag + severity 着色 Tag（critical 红 / major 橙 / 其余灰）+ 状态 Tag（disposition：resolved 等终态绿「已解决」、pending 蓝「处置中」；escalation：handled 绿「已处理」/ 未处理橙）；标题行下 `description` 一句话摘要（Typography.Text ellipsis 截断），不渲染 summary 全文
- [ ] 2.2 未知 kind 守卫：state/admin/run 之外的节点不渲染卡片体，不报错；移动端（isMobile）样式适配与既有卡片一致

## 3. 收尾验证

- [ ] 3.1 全量测试套件回归零新增失败；SPEC 详情接口实查：构造/选取含 admin 记录的项目验证 `timeline[]` 中 admin 节点字段完整、排序正确
