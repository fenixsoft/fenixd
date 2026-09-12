# 验证报告：fix-dashboard-fault-isolation

> ⚠️ 本报告由框架于 2026-09-12T08:24:41Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 6/10 场景通过，4 失败，0 错误（1 个真实产品 Bug）**

1 个产品缺陷（副标题属性拼写错误）；3 个场景文件缺陷已原地修复（timeout/boolean/selector），下次验证自动生效

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 4 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 13.58M |
| 本链增量 Token（输出） | 0.11M |


## 真实产品 Bug

### BUG-01（severity=minor）· text_contains

- 关联场景：web-overview-page-loads
- 描述：概览页副标题「监控 N 个项目」未渲染：overview/index.tsx:66 使用小写 subtitle，pro-components PageHeader 属性为 subTitle，拼写错误致副标题被忽略
- 根因：src/pages/overview/index.tsx:66 subtitle 属性名拼写错误（subtitle→subTitle）
- 证据（场景 web-overview-page-loads 结构化证据，引用）：
  - failed_assertions: [{"type": "text_contains", "text": "个项目", "expected": "副标题含「个项目」", "actual": "副标题元素 .ant-page-header-heading-sub-title 在 DOM 中不存在"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/fix-dashboard-fault-isolation/screenshots/web-overview-page-loads_assert_fail.png"]
  - first_failed_step: 断言2 text_contains「个项目」失败：页面标题/卡片/统计卡均正常渲染（data 已加载），但 PageContainer header 副标题元素缺失——源码用小写 subtitle，正确属性为 subTitle，副标题从未渲染


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-discover-skip-unreadable | 发现层容错：probe_child 捕获 OSError（含 EIO）跳过不可读子目录并写 WARNING 日志，同扫描根正常项目与显式项目不受影响；is_dir 抛异常与扫描根整体不可读同样被隔离 | pass | 0/4 | - |
| cli-discover-ignored-before-probe | 忽略列表前置：ignored 过滤先于探测（命中 ignored 且探测会抛 OSError 的目录探测调用次数为 0），不可读路径仍可被 add_ignored 写入 | pass | 0/4 | - |
| cli-aggregation-isolation | 聚合层逐项目隔离：单项目摘要异常降级为 error 字段、不向 totals 累加、其余项目与 exists 语义不变，/api/overview 与 /api/projects 均返回 200 | pass | 0/4 | - |
| cli-cache-semantics | 发现缓存异常语义：discover 抛异常时保留上次成功结果、_cache_ts 无条件推进使 TTL 内不重复执行、首次失败返回空列表且响应 200 | pass | 0/4 | - |
| cli-overview-live-consistency | 真实实例聚合一致性：经 FENIX_VERIFY_BASE_URL GET /api/overview，校验 HTTP 200、projects 非空、totals 与各正常项目字段之和一致、无 error 项目不破坏响应 | failed（已修正） | 4/4 | test-defect |
| api-overview-returns-200 | GET /api/overview 返回 200 且结构齐备：projects 数组逐项含 name/path/discovered/exists，totals 含 spec_count/task_done/task_total/problems/active_runs 等数字字段 | pass | 0/4 | - |
| api-projects-returns-200 | GET /api/projects 返回 200：projects 数组非空，逐项含 name/path/discovered/exists/daemon | failed（已修正） | 1/4 | test-defect |
| web-overview-page-loads | 概览页正常加载与渲染：标题「跨项目概览」、副标题「监控 N 个项目」、统计卡与项目卡片容器可见（导航出处 core/dashboard/static/config/routes.ts:12 /overview 页面 core/dashboard/static/src/pages/overview/index.tsx:62-97） | failed（已修正） | 1/5 | product-bug |
| web-overview-card-enter | 交互契约：概览项目卡片「进入」按钮点击后跳转该项目列表页（源码 ProjectCards.tsx:202 进入按钮；路由 core/dashboard/static/config/routes.ts:19 /projects/:name） | failed（已修正） | - | test-defect |
| web-overview-search-filter | 交互流程：项目卡片搜索框输入过滤，「搜索项目」输入后列表收敛、输入内容回读正确（源码 ProjectCards.tsx:168-174 搜索框） | pass | 0/4 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| cli-overview-live-consistency | exit_code live_consistency 期望0 | test-defect | 测试用例自身缺陷（非产品缺陷） | 脚本 timeout=15s 小于冷启动聚合延迟（同轮 api-overview-returns-200 latency_ms=16256），超时抛异常 exit 1，非产品行为失败 |
| cli-overview-live-consistency | output_match HTTP:200 | test-defect | 测试用例自身缺陷（非产品缺陷） | 同上：异常退出无 stdout；复测实例返回 HTTP 200，实例健康 |
| cli-overview-live-consistency | output_match CONSISTENT:True | test-defect | 测试用例自身缺陷（非产品缺陷） | 同上；复测 SUM 254/2101/2224 与 totals 一致，聚合正确 |
| cli-overview-live-consistency | output_match DEGRADED:[] | test-defect | 测试用例自身缺陷（非产品缺陷） | 同上；复测 DEGRADED=[]，无降级项目 |
| api-projects-returns-200 | json_path projects[0].exists 正则^(?true\|false?)匹配 | test-defect | 测试用例自身缺陷（非产品缺陷） | JSON布尔值 true 经 str() 转为 "True"（首字母大写），正则 ^(true\|false)$ 未覆盖，json_schema 已证 exists 为 boolean，产品行为正确，属场景文件断言写法缺陷 |
| web-overview-card-enter | click .overview-project-card .ant-list-item .ant-btn-link:has-text('进 入')（步骤3 点击进入按钮） | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤3 click 报 element_not_found（Locator.wait_for 5s 超时，无断言执行）：选择器含「进 入」空格，实测 4 张卡片按钮文本为「进入」无空格；场景文件缺陷已原地修复为 :has-text('进入')，断言未动 |

## 本轮场景集变更

当前稳定场景集共 10 个（第 1 轮）。

- 首轮写入 10 个场景

