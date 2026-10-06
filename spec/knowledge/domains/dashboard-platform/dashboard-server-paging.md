# 读端点服务端分页

<!-- knowledge: capability=dashboard-server-paging rev=1
     sources=spec/archive/2026-10-07-add-dashboard-paging-and-etag -->

`/api/admin-activities` 与 `/api/specs` 的服务端分页契约：数据变化时只传请求页，不再为渲染一页传输全量。

## 规则

- `/api/admin-activities` 支持 `page`（1 起）与 `page_size`（默认 50，上限 200，非法/超限钳制回默认或上限）：分页在跨项目合并排序**之后**切片；带 `page` 时响应为 `{"projects": [...], "total", "page", "page_size", "has_more"}`，`projects[]` 仅含当前页记录（按项目分组、组内保持全局相对顺序，前端按同语义平铺后即全局序）；`total` 为全量合并后总条数；`has_more = total > page*page_size`。`?project=X` 单项目路径同样支持分页；`page` 越界返回空页且 `has_more=false`。
- 跨项目全局排序在服务端完成且逐条复刻前端语义：`handled === false` 未处理置顶 → `created` 非法/缺失归一 0 → 组内 `created` 倒序。置顶先于分页：置顶记录 MUST 全部出现在第一页，不被切到后续页。不变量：任意页内容 ≡ 全量响应的对应区段。
- `/api/specs?project=X` 支持 `page`/`page_size`（默认 200，上限 500）：按现有排序输出切片，带 `page` 时响应追加 `total`/`page`/`page_size`/`has_more`。
- 向后兼容是硬契约：不带 `page` 参数时两端点响应结构与基线逐字段一致（specs 缺省响应不追加 `total` 等字段），现有调用方零改动可用。
- 前端运维页 `/activities` 采用 API 翻页：数据加载携带 `page`/`page_size=15`，翻页直接请求对应页，无全量拉取；SSE refresh 触发的刷新重拉**当前页**（页码不跳回第 1 页）；页面顶部总数徽标读响应 `total`。
- 范围边界：`/api/alerts` 与 `/api/config` 不做分页——告警闭环视图需要全量语义，config 天然小。

## 关键行为

- 全量合并 120 条请求 `page=2&page_size=50`：返回第 51–100 条（与全量响应对应区段逐条一致），`total=120`、`has_more=true`。
- 项目 520 个 spec 请求 `page=3&page_size=200`：返回第 401–520 个摘要，`total=520`、`has_more=false`。
- 运维页从第 1 页翻到第 2 页：发出 `page=2&page_size=15` 请求并渲染第 2 页，期间无全量拉取；停留第 3 页期间收到 refresh 事件，请求仍携带 `page=3`。

## 溯源

- 2026-10-07 add-dashboard-paging-and-etag（spec/archive/2026-10-07-add-dashboard-paging-and-etag） — 新增 admin-activities 与 specs 服务端分页及运维页 API 翻页，替代前端「全量拉取 + 本地切片」模式
