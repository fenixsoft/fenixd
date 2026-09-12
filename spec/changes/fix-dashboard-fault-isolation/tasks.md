## Deliverables

```yaml
- path: core/dashboard/registry.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/pages/overview/index.tsx
  kind: modify
- path: tests/test_dashboard_fault_isolation.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 发现层容错（project-discovery）

- [x] 1.1 在 `core/dashboard/registry.py` 增加统一的子目录探测 helper：把目录类型判断（`is_dir()`）与 `.fenix/STATE.md` 存在性探测（`is_file()`）一并包进捕获 `OSError` 的逻辑，返回三态（存在 / 不存在 / 不可读）；`ENOENT`/`ENOTDIR` 等正常「不存在」分支 MUST 静默，其余 `OSError`（含 `EIO`）MUST 写一条 WARNING 日志，内容至少含路径与 errno/异常摘要。实现须显式 `try/except OSError`，MUST NOT 依赖 `pathlib` 默认吞异常（其 `_IGNORED_ERROS` 不含 `EIO`）
- [x] 1.2 `discover()` 的子目录循环改用 1.1 的 helper：命中「不可读」时跳过该子目录并继续遍历其余子目录，`discover()` MUST 正常返回而非抛出；显式 `projects` 的构造路径 MUST NOT 受扫描异常影响（显式项目始终出现在结果中）
- [x] 1.3 `ignored` 过滤前移到任何触盘探测**之前**：循环内先计算规范化 key（复用既有 `_norm()` 语义并保持与写入侧一致）、与 `ignored` 比对命中即 `continue`，之后才允许做 `is_dir()` / `.fenix/STATE.md` 探测
- [x] 1.4 复核 `Registry.add_ignored(path)` 对**目录不可读**的路径仍可成功写入（`_norm()` 走非 strict `resolve()`，不得因目标不可读而返回失败）
- [x] 1.5 扫描根整条不可读（`iterdir()` 抛 `OSError`）时跳过该扫描根、继续处理其余扫描根与显式项目的行为保持不变，补一条断言覆盖
- [x] 1.6 单测（写入 `tests/test_dashboard_fault_isolation.py`）：以 monkeypatch/mock 让某子目录的探测抛 `OSError(EIO)`，断言 `discover()` 不抛异常、该目录不在结果中、同扫描根下正常 Fenixd 项目仍被发现、显式项目仍存在；断言 WARNING 日志被写出
- [x] 1.7 单测：对同一子目录先写入 `ignored`，再让探测抛 `OSError`，断言探测函数调用次数为 0（忽略过滤短路），且 `discover()` 正常返回

## 2. 聚合层与服务层隔离（dashboard-server）

- [x] 2.1 `core/dashboard/data.py` 的 `overview()`：跨项目循环体逐项目 `try/except`，失败项目的摘要 MUST 带非空 `error` 字段（描述原因）、MUST NOT 向 `totals` 的任何计数累加、MUST NOT 触发 `active_runs_by_type` / `status_counts` / `token_entries` 的贡献；其余项目与 `totals` 照常返回，函数不得抛出
- [x] 2.2 `core/dashboard/server.py` 的 `_api_projects()`：同样逐项目隔离，失败项目带 `error` 字段，其余项目正常列出，端点 MUST 返回 200
- [x] 2.3 `DashboardHTTPServer.projects()` 加发现异常兜底：`registry.discover()` 抛异常时保留 `_projects_cache` 原值（从未成功过则为空列表）并记录错误，异常 MUST NOT 冒泡；`_cache_ts` MUST **无条件**推进，使 TTL 内后续请求复用上次结果而非每请求重试
- [x] 2.4 单测：`discover()` 持续抛异常时，TTL（10s）内多次请求 `/api/overview`，断言 `discover()` 调用次数为 1、响应 200、项目列表等于上次成功结果；首次即失败时断言 200 且项目列表为空数组
- [x] 2.5 单测：构造一个项目摘要计算抛异常的假项目与一个正常项目，断言 `/api/overview` 返回 200、失败项目带 `error`、正常项目字段与 `totals` 与无故障时一致
- [x] 2.6 单测：断言 `exists` 语义未被改动——路径可解析但内容不可读的项目仍为 `exists=True`，失败原因只体现在 `error` 字段

## 3. 前端降级展示（dashboard-overview）

- [x] 3.1 `core/dashboard/static/src/pages/overview/index.tsx`：请求失败时 MUST NOT 清空已成功加载的 `data`，错误提示叠加在既有数据之上展示
- [x] 3.2 首屏失败（`data` 为 null 且有错误）时展示错误提示与「重试」入口，触发重试 MUST 重新发起 `/api/overview` 请求；MUST NOT 停留在空白页或永久加载态
- [x] 3.3 项目卡片渲染支持摘要中的 `error` 字段：非空时呈现错误态（警示色 + 原因文案）并带错误标记，MUST NOT 以正常 daemon 徽标 / 进度数字形态呈现；该卡片 MUST 仍出现在概览中，且其存在 MUST NOT 影响其它卡片与 `totals` 的渲染
- [x] 3.4 重建前端产物（`core/dashboard/static/dist/index.html`）并确认产物包含本次改动

## 4. 回归与端到端验证

- [x] 4.1 运行 `tests/test_dashboard_fault_isolation.py` 全绿
- [x] 4.2 运行既有 `tests/test_dashboard_api.py`、`tests/test_dashboard_data.py`，确认无回归
- [x] 4.3 端到端复现 2026-09-12 事故场景：在扫描根下放置一个探测即抛 I/O 错误的目录（等价物：不可读目录或 monkeypatch 到真实 `discover()` 调用链），确认修复前 `/api/overview` 为 500、修复后为 200 且其余项目卡片正常
- [x] 4.4 端到端确认逃生通道可用：把该坏目录路径写入 `dashboard.yaml` 的 `ignored` 后，`discover()` 不再触发其探测，概览正常
- [x] 4.5 经 `:8787` 实跑概览页，确认单项目错误态卡片可显示、刷新失败不清空已展示数据、「重试」入口可用（对照本项目 dist/src 漂移教训，必须以实际服务产物为准）## 验证修复（原地打回第 2 轮）

- [ ] 先复核失败有效性：逐条核对 `spec/changes/fix-dashboard-fault-isolation/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [ ] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [ ] 修复后重跑验证确认通过
