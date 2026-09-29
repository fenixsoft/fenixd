## Deliverables

```yaml
- path: core/dashboard/data/signature.py
  kind: new
- path: core/dashboard/routes/base.py
  kind: modify
- path: core/dashboard/routes/alert_routes.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/activities/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: tests/test_dashboard_api.py
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 数据源签名与条件请求（后端）

- [ ] 1.1 新建 `core/dashboard/data/signature.py`：实现 `file_sig(path) -> tuple`（`(mtime_ns, size)`，带 memo 缓存，键含 path）、`data_signature(proot, sources) -> str`、`data_signature_all(project_roots) -> str`（组合哈希），签名计算不读文件内容、只 stat
- [ ] 1.2 `routes/base.py` JSON 适配层接入 ETag 分派：GET 端点注册表支持挂签名函数；请求带 `If-None-Match` 且命中时经与 `_json` 同一写出路径返回 304（`ETag` 头 + 空体 + Content-Length: 0，keep-alive 不污染），未命中返回 200 并附 `ETag` 头；304 分支在响应体序列化之前短路
- [ ] 1.3 五个读端点接入：`/api/overview`、`/api/specs`、`/api/admin-activities`、`/api/alerts`、`/api/config`（含 `?project=` 变体）按 proposal 签名源表挂接；`?project=X` 变体的签名只依赖该 X 的数据源
- [ ] 1.4 `tests/test_dashboard_api.py` 新增条件请求用例：未变命中 304（空体≤1KB）、数据源 mtime 变化后 200 新 ETag、无条件请求响应体与改造前一致、304 响应可复用同一 keep-alive 连接继续请求

## 2. 服务端分页（后端）

- [ ] 2.1 `routes/alert_routes.py` `_api_admin_activities` 聚合路径与 `?project=` 路径支持 `page`/`page_size`（默认 50、上限 200，非法值回退默认）：合并排序后切片，带 `page` 时响应追加 `total`/`page`/`page_size`/`has_more`，缺省 `page` 时响应结构与改造前逐字段一致；置顶语义先于切片
- [ ] 2.2 `/api/specs`（base.py `_get_specs` 路径）支持 `page`/`page_size`（默认 200、上限 500，非法值回退默认）：现有排序后切片，带 `page` 时追加 `total`/`page`/`page_size`/`has_more`，缺省时响应零变化
- [ ] 2.3 `tests/test_dashboard_api.py` 新增分页用例：任意页内容 ≡ 全量响应对应区段（逐条一致）、120 条取 page=2/page_size=50 边界、非法 page/page_size 回退默认、缺省响应逐字段与改造前一致、置顶记录全部落在第一页

## 3. 前端接入

- [ ] 3.1 `services/dashboard.ts` 请求层加模块级 ETag 缓存（`Map<完整URL含query, {etag, data}>`）：GET 自动带 `If-None-Match`，304 返回缓存数据（对调用方透明），200 更新缓存；提供测试注入口或在 `core/dashboard/static/tests/` 增加单测（mock fetch 304 路径返回缓存数据）
- [ ] 3.2 `pages/activities/index.tsx` 翻页改走服务端分页：`load()` 携带 `page`/`page_size=15`，翻页请求对应页，总数读 `total`，SSE 刷新重拉当前页（页码不跳回第 1 页），「未处理置顶」展示语义由服务端排序保证不变
- [ ] 3.3 `pages/projects/detail.tsx` 心跳刷新路径确认走 `request()` 封装（命中 304 通道）：若存在绕过封装的直连 fetch 改为封装调用；页面渲染结果在无数据变化时不重渲染

## 4. 构建与回归

- [ ] 4.1 前端构建产物重建并落位 `core/dashboard/static/dist/`（构建在实现分支执行，dist 为 reference 不进 git 亦不影响守卫）
- [ ] 4.2 后端全量测试通过：`python3 -m pytest tests/test_dashboard_api.py tests/test_dashboard_index.py -x -q`
- [ ] 4.3 前端测试通过：`core/dashboard/static/tests/` 下既有用例 + 新增用例全绿
- [ ] 4.4 端到端冒烟：本地起 dashboard，浏览器访问 `/activities` 翻页、项目详情页停留 30s 观察条件请求 304 命中（Network 面板或 curl 验证），确认传输量较改造前下降
