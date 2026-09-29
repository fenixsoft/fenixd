<!-- knowledge: capability=v2-project-list-page rev=1 sources=spec/archive/2026-09-06-v2-project-list-page -->

# v2 SPEC 列表页

v2 的项目内 SPEC 列表：8 列渲染、三维过滤、fix 树分组与行内操作。

## 现行规则

- `/spec/project` 页 crud 渲染 8 列：状态（badge）、名称（链接 `#/spec/:project/:name`）、优先级、创建时间、任务进度、验证、耗时、文档。
- 过滤支持关键词 / 状态 / 类型（submitOnChange）；过滤状态在 crud 同步位置时保留。
- fix 树行按 children 缩进渲染：`fix-<父名>` 子任务作为父行 children 展示（缩进、聚合进度）。
- spec-crud 监听 `sse:state` 重拉。
- 每行 dropdown 行内操作：「呼叫 Admin」（打开 Admin 处置弹窗，见 v2-admin-doc-modals 能力）；「调优先级」Dialog 表单 `POST /api/spec-priority`（字段按 behavior.md §1），提交后行数据更新可见；「删除」confirm 后 `POST /api/spec-delete`，成功后重拉列表。
- 行内可打开 error 详情 Dialog：懒加载该 SPEC 的 error 与 why（behavior.md §5）；「清除错误」按钮 `POST /api/spec-error-clear`，成功后 error 消失并刷新列表。

## 溯源

- 史前复原 — v2 SPEC 列表页 8 列 + 类型过滤 + fix 树 + 行内操作；crud 同步位置时保留过滤状态
- [2026-09-06 v2-project-list-page](spec/archive/2026-09-06-v2-project-list-page/) — 落地 8 列渲染与三维过滤、fix 树 children 分组、行内操作（调优先级 / 删除）与 error 详情懒加载清除闭环
