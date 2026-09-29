## ADDED Requirements

### Requirement: admin-activities 服务端分页

`/api/admin-activities` 支持 `page`（1 起）与 `page_size`（默认 50，上限 200）参数：跨项目合并排序（未处理置顶、组内 created 倒序，与现行为一致）**之后**在服务端切片，响应体为 `{"projects": [...], "total": <全量条数>, "page": N, "page_size": M, "has_more": <bool>}`。未携带 `page` 参数时保持现有全量响应结构不变（向后兼容）。`?project=X` 单项目路径同样支持分页。

#### Scenario: 分页切片语义

- **WHEN** 全量合并后共 120 条，请求 `page=2&page_size=50`
- **THEN** 返回第 51–100 条（排序与全量响应的对应区段逐条一致），`total=120`，`has_more=true`

#### Scenario: 缺省参数向后兼容

- **WHEN** 请求不带 `page` 参数（现有前端 AdminInvokeModal、SpecDocModal 调用点）
- **THEN** 响应结构与改造前字段完全一致，包含全部记录

#### Scenario: 置顶语义先于分页

- **WHEN** 存在 3 条未处理升级关联记录，请求 `page=1&page_size=50`
- **THEN** 3 条置顶记录全部出现在第一页（不被切到后续页）

### Requirement: specs 列表服务端分页

`/api/specs?project=X` 支持 `page`/`page_size`（默认 200，上限 500）参数：按现有排序切片，响应体追加 `total`/`page`/`page_size`/`has_more` 字段；未携带 `page` 时保持现有全量结构（仅追加字段亦不允许——缺省响应保持原样，避免破坏增量 patch 前端）。

#### Scenario: 大项目分页拉取

- **WHEN** 项目有 520 个 spec，请求 `page=3&page_size=200`
- **THEN** 返回第 401–520 个 spec 摘要，`total=520`，`has_more=false`

#### Scenario: 缺省响应零变化

- **WHEN** 请求不带 `page` 参数
- **THEN** 响应 JSON 结构与改造前逐字段一致（现有项目页 spec 表格零改动可用）

### Requirement: 前端运维页翻页接 API

`/activities` 页移除「全量拉取 + 前端切片」模式：数据加载改为携带 `page`/`page_size=15` 请求；翻页/新页渲染直接请求对应页；SSE 触发的刷新重拉**当前页**。页面顶部的总数徽标读响应 `total`。

#### Scenario: 翻页走 API

- **WHEN** 用户在运维页从第 1 页翻到第 2 页
- **THEN** 发出 `page=2&page_size=15` 请求并渲染第 2 页内容，期间无全量拉取

#### Scenario: SSE 刷新保持当前页

- **WHEN** 用户停留第 3 页期间收到 refresh 事件触发重拉
- **THEN** 请求携带 `page=3`，页码不跳回第 1 页（与现行为一致）
