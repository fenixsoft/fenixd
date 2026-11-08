# provfix-seed 验证夹具滞留生产账本 + 验证实例混代 500

- 日期：2026-11-08
- 类型：排查结论
- 关联：add-provider-validation-alert-governance 验证（14/15，唯一挂 alert-panel-undo-supersede-restore）

## 现象

overview 告警横幅出现 3 条 `[provfix-seed]` 未处理告警（种子甲/乙 model-chain、种子丙 harness-cli），另 2 条 superseded 藏于 activities「告警记录」折叠组。

## 结论

1. **夹具种子是设计内写入**：场景 `seed-alert-fixtures-for-panel` 经真实 AdminStore 通道向本项目账本写 5 条种子（3 未处理 + 2 superseded），故意不打 fixture 标、进缺省跨项目聚合，供面板场景在真聚合数据上断言计数/折叠组/根因分组/撤销入口。场景幂等（按 description 去重）但**无清理步骤**，验证后滞留属设计内遗留。
2. **验证实例 500 = 新旧模块混代**：撤销路由在验证 dashboard 实例（:37941）上 500，但 `AdminStore.revert_supersede` 在当前代码副本上全对（撤销生效/二次撤销 False/不存在 id False）。判读：routes 模块有新路由、`dashboard_data` 门面缺 `revert_superseded_alert` → AttributeError。与同日「蒸馏校验假阳性=旧模块」同型，修法重启承载进程，勿改代码。
3. **生产 daemon 同样旧代**：8787 对 `/api/alerts/<id>/revert-supersede` 返回路由层 404（`{"error": "Not Found"}`）——SPEC 的新端点须 daemon 重启后上线。

## 待办

- daemon 重启后复验撤销场景（或面板手工点一次「撤销失效」确认 500 消失）。
- 种子清理路径：面板逐条处置，或直接剔除 `.fenix/admin_alerts.json` 中 5 条 `[provfix-seed]` 记录。
- 沉淀方向：验证夹具种子场景应配对清理步骤（teardown）或在场景契约中声明「遗留合法」。
