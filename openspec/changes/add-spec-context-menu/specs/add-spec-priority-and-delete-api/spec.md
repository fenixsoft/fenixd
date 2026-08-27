# add-spec-priority-and-delete-api — 优先级与软删除后端

## ADDED Requirements

### Requirement: 优先级写回 API
`POST /api/spec-priority?project=<name>&spec=<name>`，JSON body `{"priority": <int>}`。服务端校验 1-9 整数后调用 state_machine.update_spec 更新 priority 字段并返回 `{ok: true, priority: N}`；spec 不存在 404，非法值 400。

#### Scenario: 合法优先级写回
- WHEN body 为 {"priority": 2} 且 spec 存在
- THEN STATE.md 对应条目 priority=2（原子写回），响应 ok=true

#### Scenario: 非法值被服务端拒绝
- WHEN body 为 {"priority": 0} / {\"priority\": 12} / 非整数
- THEN 响应 400 含原因，STATE.md 不变

### Requirement: 软删除实现
`POST /api/spec-delete?project=<name>&spec=<name>` 执行：① state_machine 移除该 spec 条目（新增 remove_spec 方法，读全部→剔除→原子写回）；② 将 `openspec/changes/<name>/` 整目录移动到 `openspec/changes/archive/<name>-<Unix秒>/`（archive 目录不存在则创建）。任一步失败回滚 STATE.md 写入或返回 5xx 并保持数据一致。

#### Scenario: 删除后两处数据一致
- WHEN 对存在的 spec 调用删除 API
- THEN STATE.md 不含该条目且 openspec/changes/archive/<name>-<ts>/ 存在原目录全部文件

#### Scenario: spec 目录缺失时仅清状态
- GIVEN 该 spec 的 openspec 目录已不存在
- WHEN 调用删除 API
- THEN 仅移除 STATE.md 条目，响应仍 ok=true（幂等语义）

#### Scenario: 目录移动冲突可恢复
- WHEN archive 中已存在同名时间戳目录（极小概率）
- THEN 服务端在名字上追加毫秒后缀重试移动成功，不丢数据

### Requirement: 删除不受状态门禁限制
删除对任意 status（含 done、implementing、testing）可用；若存在进行中的 agent run，服务端返回 409「spec 有进行中的运行」拒绝删除，由用户先等待或手动处理。

#### Scenario: 运行中 spec 拒绝删除
- GIVEN 某 spec 有活跃的 impl/verify run 文件仍在增长
- WHEN 调用删除
- THEN 响应 409，STATE.md 与目录不变
