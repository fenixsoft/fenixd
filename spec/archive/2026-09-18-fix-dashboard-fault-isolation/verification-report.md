# 验证报告：fix-dashboard-fault-isolation

> ⚠️ 本报告由框架于 2026-09-13T10:53:07Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-12T11:54:54.370624+00:00

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 13.86M |
| 本链增量 Token（输出） | 0.11M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-discover-skip-unreadable | 发现层容错：probe_child 捕获 OSError（含 EIO）跳过不可读子目录并写 WARNING 日志，同扫描根正常项目与显式项目不受影响；is_dir 抛异常与扫描根整体不可读同样被隔离 | pass | 0/4 | - |
| cli-discover-ignored-before-probe | 忽略列表前置：ignored 过滤先于探测（命中 ignored 且探测会抛 OSError 的目录探测调用次数为 0），不可读路径仍可被 add_ignored 写入 | pass | 0/4 | - |
| cli-aggregation-isolation | 聚合层逐项目隔离：单项目摘要异常降级为 error 字段、不向 totals 累加、其余项目与 exists 语义不变，/api/overview 与 /api/projects 均返回 200 | pass | 0/4 | - |
| cli-cache-semantics | 发现缓存异常语义：discover 抛异常时保留上次成功结果、_cache_ts 无条件推进使 TTL 内不重复执行、首次失败返回空列表且响应 200 | pass | 0/4 | - |
| cli-overview-live-consistency | 真实实例聚合一致性：经 FENIX_VERIFY_BASE_URL GET /api/overview，校验 HTTP 200、projects 非空、totals 与各正常项目字段之和一致、无 error 项目不破坏响应 | pass | 0/4 | - |
| api-overview-returns-200 | GET /api/overview 返回 200 且结构齐备：projects 数组逐项含 name/path/discovered/exists，totals 含 spec_count/task_done/task_total/problems/active_runs 等数字字段 | pass | 0/4 | - |
| api-projects-returns-200 | GET /api/projects 返回 200：projects 数组非空，逐项含 name/path/discovered/exists/daemon | pass | 0/4 | - |
| web-overview-page-loads | 概览页正常加载与渲染：标题「跨项目概览」、副标题「监控 N 个项目」、统计卡与项目卡片容器可见（导航出处 core/dashboard/static/config/routes.ts:12 /overview 页面 core/dashboard/static/src/pages/overview/index.tsx:62-97） | pass | 0/5 | - |
| web-overview-card-enter | 交互契约：概览项目卡片「进入」按钮点击后跳转该项目列表页（源码 ProjectCards.tsx:202 进入按钮；路由 core/dashboard/static/config/routes.ts:19 /projects/:name） | pass | 0/4 | - |
| web-overview-search-filter | 交互流程：项目卡片搜索框输入过滤，「搜索项目」输入后列表收敛、输入内容回读正确（源码 ProjectCards.tsx:168-174 搜索框） | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 10 个（第 1 轮）。

首轮写入 10 个场景

