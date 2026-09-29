<!-- knowledge: capability=add-spec-priority-and-delete-api rev=1 sources=spec/archive/2026-09-03-add-spec-context-menu -->

# SPEC 优先级写回与软删除 API

SPEC 行右键菜单背后的两个后端端点：优先级原子写回与软删除（状态移除 + 目录归档）。

## 现行规则

- 优先级写回：`POST /api/spec-priority?project=<name>&spec=<name>`，JSON body `{"priority": <int>}`；服务端校验 1-9 整数后经 `state_machine.update_spec` 原子写回 priority 字段，返回 `{ok: true, priority: N}`；spec 不存在返回 404，非法值返回 400（含原因）且 STATE.md 不变。
- 软删除：`POST /api/spec-delete?project=<name>&spec=<name>` 执行两步——`state_machine.remove_spec` 读全部条目→剔除目标→原子写回；`spec/changes/<name>/` 整目录移动到 `spec/archive/<name>-<Unix秒>/`（archive 目录不存在则创建）。
- 一致性：任一步失败回滚 STATE.md 写入或返回 5xx 并保持数据一致；删除后 STATE.md 不含该条目且归档目录保有原目录全部文件。
- 幂等与冲突：SPEC 目录已缺失时仅移除 STATE.md 条目、响应仍 ok=true（幂等语义）；归档目标已存在同名时间戳目录时追加毫秒后缀重试移动，不丢数据。
- 删除不受状态门禁限制：任意 status（含 done、implementing、testing）可删；存在进行中的 agent run 时返回 409「spec 有进行中的运行」，STATE.md 与目录不变，由用户先等待或手动处理。

## 溯源

- 史前复原 — 优先级写回与软删除后端 API 基线（`state_machine.remove_spec` 原子移除）
- [2026-09-03 add-spec-context-menu](spec/archive/2026-09-03-add-spec-context-menu/) — 固化 /api/spec-priority 与 /api/spec-delete 契约：目录缺失幂等、归档时间戳冲突毫秒后缀重试、在飞 run 409 拒绝删除
