## ADDED Requirements

### Requirement: SPEC 列表渲染与过滤

/spec/project 页 crud 渲染 8 列(behavior.md §2 逐字):状态(mapping badge)、名称(链接 #/spec/:project/:name)、优先级、创建时间、任务进度、验证、耗时、文档;filter 支持关键词/状态/类型(submitOnChange);fix 树行按 children 缩进渲染;spec-crud 监听 sse:state reload。

#### Scenario: 列表与过滤
- **WHEN** 访问 #/project/<真实项目名> 并在关键词框输入已知 SPEC 名片段
- **THEN** 8 列可见,过滤后仅匹配行可见;状态行是可点链接

#### Scenario: fix 树分组
- **WHEN** 项目存在 fix-<父名> 子任务
- **THEN** 子行作为父行 children 展示(缩进、聚合进度)

### Requirement: 行内操作

每行 dropdown 含:呼叫 Admin(本 SPEC 占位 toast)、调优先级(Dialog 表单 POST /api/spec-priority,字段 behavior.md §1)、删除(confirm 后 POST /api/spec-delete,成功后 reload spec-crud)。

#### Scenario: 调优先级
- **WHEN** 行内操作 → 调优先级 → 填值提交
- **THEN** POST 发出且行数据更新后可见

#### Scenario: 删除
- **WHEN** 行内操作 → 删除 → confirm
- **THEN** POST /api/spec-delete 发出,列表重拉

### Requirement: error 详情与清除

行内可打开详情 Dialog:懒加载该 SPEC 的 error 与 why(behavior.md §5);含「清除错误」按钮(POST /api/spec-error-clear)成功后 reload。

#### Scenario: Why 懒加载与清除
- **WHEN** 打开有 error 的 SPEC 详情 Dialog
- **THEN** error 文本与 why(懒加载)可见;点击清除后 error 消失且列表刷新
