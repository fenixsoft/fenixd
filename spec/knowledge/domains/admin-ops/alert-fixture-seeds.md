# 告警面板验证夹具种子

<!-- knowledge: capability=alert-fixture-seeds rev=1
     sources=spec/knowledge/_inbox/done/provfix-seed-fixture-residue-and-verify-instance-mixed-vintage-500.md -->

告警面板类验证场景的夹具供给契约：种子经真实 AdminStore 通道写入承载验证实例的自身项目账本，滞留生产账本属设计内遗留；`[provfix-seed]` 前缀是残留种子的判别签名。

## 规则

- **真实通道写入、不打 fixture 标**：面板场景前置 `seed-alert-fixtures-for-panel` 经 `AdminStore` 真实读写通道向验证实例自身项目账本（`.fenix/admin_alerts.json`，cwd=验证树根）写入 5 条 escalation 种子——3 条未处理（cause=model-chain ×2、harness-cli ×1，description 刻意不含根因词避免断言自证）＋ 2 条已失效（cause=model-chain，handled_by=superseded）。种子故意不打 fixture 标、进缺省跨项目聚合，面板场景据此在真聚合数据上断言计数、折叠组、根因分组与撤销入口。
- **幂等含未处理态恢复**：种子按 description 去重可重入；重入时经 `update_records` 把 3 条未处理种子重置回未处理态（实例自身告警收口链会把两轮之间的种子逐条收走，幂等只保存在性会致重入失配），刻意失效种子与非种子记录不受触碰。
- **无清理步骤，滞留属设计内遗留**：场景不配 teardown，验证完成后 5 条种子滞留账本是设计内行为。
- **判别签名**：overview 告警横幅出现 `[provfix-seed]` 前缀未处理告警（对应 superseded 条目收在 activities「告警记录」折叠组）即验证夹具种子残留，不按生产告警处置、不触发归因排查。
- **清理路径**：面板逐条人工处置，或直接剔除项目 `.fenix/admin_alerts.json` 中 `[provfix-seed]` 前缀的 5 条记录。

## 代码锚点

- 主实现：`core/admin_store.py`（AdminStore——告警账本读写单源，种子经真实通道落账）
- 单源符号：`core/dashboard/data/admin_alerts.py:revert_superseded_alert`（种子所供给观测面的撤销失效实现）
- 消费方：`core/dashboard/routes/alert_routes.py`（/api/alerts 路由聚合读侧与撤销端点）；`core/dashboard/data/__init__.py`（dashboard_data 门面统一导出）
- 守卫测试：`tests/test_alert_supersede.py`、`tests/test_dashboard_data_modules_contract.py`；场景载体为 add-provider-validation-alert-governance 验证集内的 seed-alert-fixtures-for-panel 前置场景（SPEC 目录随归档迁移，不锚文件路径）

## 溯源

- 2026-11-08 provfix-seed-fixture-residue-and-verify-instance-mixed-vintage-500（spec/knowledge/_inbox/done/provfix-seed-fixture-residue-and-verify-instance-mixed-vintage-500.md） — 新建本页：种子真实通道写入契约（不打标进缺省聚合）、幂等含未处理态恢复、无 teardown 设计内遗留、`[provfix-seed]` 判别签名与两条清理路径
