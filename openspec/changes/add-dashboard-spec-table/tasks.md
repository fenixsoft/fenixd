# Tasks: Dashboard 项目 SPEC 列表表格化 + 排序 + 过滤

## 1. 数据层与 API

- [x] 1.1 在 `core/dashboard/data.py::spec_summary` 增加 `"created": entry.get("created")` 与 `"updated": entry.get("updated")` 字段（缺失为 null）
- [x] 1.2 将 `core/dashboard/server.py::_api_specs` 排序改为创建时间倒序：`created` 倒序（新在前），`created` 缺失（null）的 SPEC 排最后

## 2. 前端表格化

- [x] 2.1 改造 `core/dashboard/static/app.js::renderProject`：将 spec-row div 列表改为 `<table class="spec-table">`，`<thead>` 表头「状态 / 名称 / 优先级 / 创建时间 / 任务进度 / 验证 / 错误」，`<tbody>` 每行保留状态 pill、名称、P<优先级>、创建时间（`fmtDate`，缺失显示 `—`）、任务进度条与计数、验证计数（无验证显示 `—`）、错误 tag、点击进详情
- [x] 2.2 前端在 `renderProject` 中按 created 倒序再次排序（防御性，缺失 created 排最后），确保展示顺序与需求一致
- [x] 2.3 在 `core/dashboard/static/style.css` 新增 `.spec-table` / `.spec-table-wrap`（横向溢出滚动）/ 表头样式，沿用现有颜色变量与设计语言

## 3. 前端过滤

- [x] 3.1 项目视图新增过滤条：名称关键字输入框（占位符「搜索名称…」）+ 状态下拉（「全部状态」+ STATUS_META 各状态）；过滤逻辑为前端，基于已排序数组执行（名称大小写不敏感包含匹配 + 状态精确匹配），保留排序顺序
- [x] 3.2 过滤状态模块级持久化（如 `specFilter = {q, status}`）：自动刷新重渲染后控件回填且过滤条件仍生效；过滤结果为空展示「无匹配的 SPEC」空态（区别于「该项目暂无 SPEC」）

## 4. 测试与验证

- [x] 4.1 单元测试：`spec_summary` 输出含 created/updated；`_api_specs` 排序为 created 倒序且缺失排最后（可提取排序函数或直接测端点）
- [x] 4.2 运行 `python3 -m pytest tests/ -q` 全量通过，无回归
- [x] 4.3 端到端验证（重启 dashboard 后）：浏览器打开项目视图确认表格渲染与表头、创建时间倒序、名称/状态/组合过滤、过滤为空空态、自动刷新后过滤状态保持
