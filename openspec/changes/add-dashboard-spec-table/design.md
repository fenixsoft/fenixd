# Design: Dashboard 项目 SPEC 列表表格化 + 排序 + 过滤

## Context

项目视图当前渲染（`core/dashboard/static/app.js::renderProject` / `specRow`）：

- `specs.map(specRow)` 渲染为 `.spec-row` div 列表，无表头、无创建时间列。
- 每行展示：状态 pill、名称、`P<priority>`、任务进度条、任务数、验证数（有验证时）、错误 tag。
- 数据来自 `GET /api/specs?project=<name>`，`server.py::_api_specs` 对 `spec_summary` 列表排序为 `(status != "pushed", priority)`。
- `spec_summary`（`data.py`）当前输出 name/status/priority/error/task_done/task_total/verify_done/verify_total/verify_error/scenario_count/latest_run/latest_run_status，**不含 `created`**；但 `entry`（STATE.md 条目）有 `created` / `updated`（`parse_state` 解析，detail 视图 `renderSpec` 已用 `d.created`/`d.updated`）。

用户确认：创建时间**倒序（新在前）**；过滤维度**名称搜索 + 状态过滤**；作用域为**项目 SPEC 列表视图**。

## Goals / Non-Goals

**Goals:**
- 项目 SPEC 列表以带 `<thead>` 表头的 `<table>` 展示，每列有含义说明。
- 按创建时间倒序（新在前）。
- 前端过滤：名称关键字 + 状态；纯前端，保留排序顺序；过滤状态在 2s 自动刷新间保持。
- 数据层暴露 `created` / `updated`。

**Non-Goals:**
- 不改动跨项目概览视图（`renderOverview` 项目卡片）。
- 不做服务端过滤（用户明确「前端过滤即可」；数据量小）。
- 不新增优先级过滤（用户未选）。
- 不改变 SPEC 状态机、调度等核心逻辑。

## Decisions

### D1: 数据层暴露 created / updated

`spec_summary` 增加 `"created": entry.get("created")` 与 `"updated": entry.get("updated")`（ISO 字符串，可能为 None）。向后兼容：新增字段不影响现有字段消费。

- **理由**：前端排序与展示都需要 `created`；`entry` 已解析好，仅需透出。

### D2: 排序 —— 服务端默认改创建时间倒序，前端再确认排序

- `server.py::_api_specs` 排序改为：`created` 倒序（新在前），`created` 缺失的 SPEC 排最后（视为最旧）。
- 前端 `renderProject` 在拿到 `specs` 后同样按 created 倒序排一次（防御性，与过滤逻辑共存——过滤在排序后的数组上进行，保留排序顺序）。
- **替代方案**：仅前端排序不动服务端 —— 被否：`/api/specs` 是列表唯一数据源，服务端排序使 API 自洽且对其它潜在消费方一致。

### D3: 表格化 + 表头

`renderProject` 输出改为：

```html
<div class="spec-table-wrap">
  <table class="spec-table">
    <thead>
      <tr>
        <th>状态</th><th>名称</th><th>优先级</th><th>创建时间</th>
        <th>任务进度</th><th>验证</th><th>错误</th>
      </tr>
    </thead>
    <tbody>${specs.map(row).join('')}</tbody>
  </table>
</div>
```

- 表头语义：**状态**（SPEC 生命周期状态）、**名称**（SPEC 标识，点击进入详情）、**优先级**（P1 最高）、**创建时间**（`fmtDate(s.created)`，缺失显示 `—`）、**任务进度**（已完成/总数 + 进度条）、**验证**（验证通过/总数，无验证显示 `—`）、**错误**（最近错误摘要，无则空）。
- 每行保留 `specRow` 的点击进详情行为与状态 pill、进度条、错误 tag 等既有视觉元素。
- 样式沿用 `style.css` 现有设计语言（`.spec-row` 视觉迁移到 `.spec-table` 行，新增 thead 样式）。

### D4: 前端过滤（名称 + 状态），状态跨刷新保持

- 过滤条（渲染于表格上方）：名称 `<input>`（占位符「搜索名称…」）+ 状态 `<select>`（「全部状态」+ STATUS_META 各状态）。
- 过滤逻辑：在排序后的 `specs` 上执行——
  - 名称：`s.name.toLowerCase().includes(keyword.toLowerCase())`。
  - 状态：选择非「全部状态」时 `s.status === selected`。
- 过滤状态持久化：存于模块级变量（如 `specFilter = {q: "", status: ""}`），`renderProject` 重渲染时读取并回填过滤条控件值；自动刷新只替换表格数据，不重置过滤状态。
- 过滤后为空 → 显示「无匹配的 SPEC」空态（区别于「该项目暂无 SPEC」）。
- 输入框监听 `input` 事件、下拉监听 `change` 事件，触发局部重渲染（不整页刷新、不打断滚动位置——沿用现有刷新体验约束）。

### D5: 样式

`style.css` 新增：`.spec-table`（表头背景、行 hover、列对齐）、`.spec-table-wrap`（横向溢出滚动容器）、`.spec-filter`（过滤条 flex 布局）。表头与行采用现有颜色变量（`--fg`、`--border`、`--bg2` 等）保持一致观感。

## Risks / Trade-offs

- [created 缺失导致排序乱序] → D2 缺失 created 排最后；`STATE.md` 由 `add_spec` 写入 `created`，正常流程必有值，仅历史手工条目可能缺失。
- [自动刷新重绘打断过滤输入] → D4 过滤状态模块级持久化 + 输入/下拉受控回填，重渲染后控件值保留。
- [表格列多导致窄屏溢出] → `.spec-table-wrap` 横向滚动，移动端/窄窗口可横向滚动而非挤坏布局。
- [`/api/specs` 排序变化影响其它消费方] → 仅 dashboard 前端消费该端点；排序变化为预期 feature 变更。

## Migration Plan

1. `data.py::spec_summary` 暴露 `created`/`updated`。
2. `server.py::_api_specs` 排序改 created 倒序（缺失最后）。
3. `app.js`：`renderProject` 表格化 + 表头 + 过滤条 + 过滤状态持久化；`style.css` 新增表格/过滤样式。
4. 测试：`spec_summary` 含 created；`/api/specs` 排序断言；浏览器端到端验证表格渲染、表头、名称/状态过滤、刷新保持。
5. 重启 dashboard 后生效（常驻进程需重启加载新代码）。

## Open Questions

- 表头是否需要支持点击列排序切换（正/倒序）——本 SPEC 只做固定「创建时间倒序」，列排序切换为后续增强。
