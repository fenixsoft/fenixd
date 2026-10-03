# 验证报告：add-project-architecture-tab

> ⚠️ 本报告由框架于 2026-09-25T10:52:58Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-25T10:52:58.478978+00:00

## 结论：✅ 通过（verified）

**状态：verified — 17/17 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 17/17 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 17 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.42M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-arch-unit-tests | 架构图生命周期治理与产物判定契约单元测试：pytest 运行 tests/test_dashboard_architecture_api.py（tasks 3.1 规定覆盖：受理异步落盘与 ready / 在飞重复 POST 409 / 产物缺失自述完成判 failed / 组件数越界判 failed / skill 安装失败 error 带安装命令 / 超时进程组击杀 / 重启残留 generating 合成中断 / failed 后重试覆盖旧错误）。真实 spawn（claude -p + archify 分钟级、npx 安装依赖外网）不可在验证窗口确定性驱动，治理 MUST 路径以本单测为权威载体（对齐 add-test-regression-tab 先例）。同时校验文档交付物 docs/help/08-dashboard.md 含「项目架构」小节（tasks 3.3）。 | pass | 0/4 | - |
| cli-seed-clean-arch | 清理夹具项目 scheduling-showcase 的架构产物目录 /root/scheduling-showcase/.fenix/architecture/（status.json + diagram.html，design.md D2 产物族），为「从未生成 none」各场景提供确定性初态（对齐 add-test-regression-tab cli-clean-snapshot 先例）。夹具项目根来自 .fenix/verify.yaml prepare 段声明（fixture_scheduling_showcase.py --reset 供给至 /root/scheduling-showcase，仓外运行时目录）。 | pass | 0/2 | - |
| api-arch-status-unknown-project | GET /api/architecture/status?project=no-such-project-xyz → 404（未注册项目按本库 mixin 惯例 project not found，regression_routes.py:159/182/225 同款 _error(404,...)）。「对所有注册项目一律可用」（spec.md:8）的边界：未注册项目不得 500 也不得伪造状态。 | pass | 0/1 | - |
| api-arch-status-none | GET /api/architecture/status?project=scheduling-showcase → 200 且 state=="none"（从未生成）。spec.md「首次进入页签看到空态而非自动生成」的后端半边（后端状态查询返回 none）；端点契约 spec.md:87-89、tasks 1.1（mixin 形态，query 传 project）。 | pass | 0/2 | - |
| api-arch-diagram-not-generated | state=none 时 GET /api/architecture/diagram?project=scheduling-showcase → 结构化错误（spec.md:99-102「diagram 端点对未生成项目返回可识别错误」）。状态码按本库「资源缺失」惯例取 404（regression_routes.py:159 同款）；结构化 = JSON 错误体（base.py _error 写 {"error": msg} 且 Content-Type application/json）。前端此时不得渲染 iframe。 | pass | 0/2 | - |
| web-arch-tab-order-gating | 页签插入位置与按需加载门控（spec.md:20-24）：项目详情页 ?tab=dev 直开（页签状态经 URL tab 参数持久化，list.tsx:796-809），断言 ① 共 5 个页签（既有 4 个不动 + 新增 1 个）② 「项目架构」位于「测试回归」之后（~ 兄弟组合器）③ 位于「会话接入」之前 ④ dev 页签下「刷新架构图」按钮不在 DOM——架构分面未激活不渲染内容（antd Tabs 惰性挂载 + ArchitectureTab active 门控），是「未选中零请求」的可观察代理。导航出处：SPA 路由 /projects/:name（core/dashboard/static/config/routes.ts:27，hash 形态先例 add-cancelled-spec-resume-action）；页签数组 list.tsx:1385-1413（插入点 regression=1399 与 session=1407 之间）；.ant-tabs-tab 选择器先例 add-test-regression-tab 同款（antd Tabs 真实渲染结构）。 | pass | 0/5 | - |
| web-arch-none-empty-state | 从未生成时空态渲染（spec.md:14-18）：?tab=architecture 直开从未生成的项目，「刷新架构图」按钮可见（按钮文案为 SPEC 契约字面量）、tab 标签「项目架构」可见（label 为 SPEC 契约字面量 spec.md:7-8）、不渲染 iframe（无自动生成、无产物）。点击按钮会真实 spawn（npx/claude 分钟级不可确定驱动），触发链路由 api-arch-refresh-accept-async 与单测覆盖，此处只断空态呈现。出处：路由 routes.ts:27；页签 list.tsx:1385-1413；空态要求 spec.md:11-12。 | pass | 0/3 | - |
| cli-seed-ready-arch | 向夹具项目写入「就绪态」种子产物：/root/scheduling-showcase/.fenix/architecture/{status.json, diagram.html}。status.json 按 design.md D2 结构（state/generated_at/started_at/error/duration_ms/component_count），state=ready、component_count=10（落在 8–16 合法区间）；diagram.html 为自包含 HTML（<!DOCTYPE html 特征，spec.md:80 判定链第二环）并携带 ARCH-SEED-DIAGRAM-MARKER 标记。供 ready 四态 api/web 场景确定性驱动——真实 archify 生成（claude -p 分钟级 + npx 安装外网依赖）不可在验证窗口确定完成，产物渲染契约改由种子产物驱动（seed 的是夹具数据而非被测端点，端点全部打真实实例）。 | pass | 0/2 | - |
| api-arch-status-ready | 就绪态下 GET /api/architecture/status?project=scheduling-showcase → 200，state=="ready"、component_count==10（种子值，落在 8–16 合法区间）、generated_at 与种子一致——验证状态读侧回传生成元信息（spec.md:87-89「返回 state、generated_at、失败原因等」）。 | pass | 0/4 | - |
| api-arch-diagram-served | 就绪态下 GET /api/architecture/diagram?project=scheduling-showcase → 200 下发 diagram.html，Content-Type 含 text/html（spec.md:89-90「下发 diagram.html，Content-Type text/html」），响应体含种子标记 ARCH-SEED-DIAGRAM-MARKER（产物字节真经该端点下发，非前端伪造）。 | pass | 0/3 | - |
| web-arch-ready-iframe-sandbox | 就绪态沙箱渲染（spec.md:93-97）：?tab=architecture 直开种子 ready 项目，断言 iframe[sandbox="allow-scripts"] 可见且 sandbox 属性恰为 allow-scripts（MUST 不带 allow-same-origin，spec.md:91）、「刷新架构图」按钮仍可见（可再次点击）。产物内容经真实 diagram 端点进入 iframe（端点契约由 api-arch-diagram-served 覆盖；iframe 跨源内容不可跨帧断言，故不断言其内部 DOM）。说明卡片等 archify 产物内部元素为纯展示内容（辅助信息进说明卡片、不加连线，spec.md:70-72），声明为不可交互。出处：路由 routes.ts:27；iframe 契约 spec.md:91-93、tasks 2.2。 | pass | 0/3 | - |
| cli-seed-failed-arch | 向夹具项目覆写「失败态」种子 status.json（state=failed，error 携带独特标记 SEED-ARCH-FAIL-01，component_count=null），供 failed 态 api/web 场景确定性驱动。依赖排在 ready 态场景之后（覆写会消除 ready 态）。 | pass | 0/2 | - |
| api-arch-status-failed | 失败态下 GET /api/architecture/status?project=scheduling-showcase → 200 且 state=="failed"、error 字段含种子标记 SEED-ARCH-FAIL-01（读侧回传失败原因，spec.md:87-89「失败原因等」）。 | pass | 0/3 | - |
| web-arch-failed-error-retryable | 失败态渲染与可重试（spec.md:110-112）：?tab=architecture 直开种子 failed 项目，断言错误信息渲染（text_contains 种子错误标记 SEED-ARCH-FAIL-01——错误文案 SPEC 未约定字面量，用自己种入的错误串做 verbatim 渲染断言避免词表幻觉）、「刷新架构图」按钮恢复可点（element_enabled）、不渲染 iframe。失败后点击重试的受理链路由单测覆盖（tasks 3.1），此处不点击（会真实 spawn）。出处：路由 routes.ts:27；failed 渲染要求 spec.md:112、tasks 2.2。 | pass | 0/4 | - |
| cli-seed-generating-residue | 向夹具项目覆写「重启残留」种子 status.json（state=generating、started_at=2 小时前、error/component_count=null，模拟 daemon 重启杀掉在飞生成后的残留文件），供「读侧合成为中断 failed」MUST（spec.md:109-110/124-127）的确定性 E2E：验证实例的 ArchitectureManager 内存中无该项目的在飞进程句柄，读到残留 generating 须合成为 failed 且按钮可重试，不得永久停留 generating（无死态保证）。依赖排在 failed 态场景之后。 | pass | 0/2 | - |
| api-arch-residue-synthesized-failed | 重启残留合成（spec.md:109-110/124-127 MUST）：status.json 残留 state=generating（cli-seed-generating-residue 写入，started_at 2 小时前）且验证实例内存无在飞进程 → GET status MUST 合成为 failed（生成被中断），不得返回 generating 永久滞留。这是「无死态」保证的确定性 E2E——真实 daemon 重启时序无法在验证窗口构造，以文件残留等价驱动同一条读侧合成路径。 | pass | 0/2 | - |
| api-arch-refresh-accept-async | POST /api/architecture/refresh?project=scheduling-showcase 异步受理契约（spec.md:33-34 MUST「POST 端点 MUST NOT 在 HTTP 线程内同步等待生成完成」+ 37-40「POST 立即返回受理结果」）：响应快速返回（latency_under 5000ms）且受理成功。成功码取 200（mixin _json 缺省、regression_routes.py:221/332 异步受理先例「受理 → 200 + {ok,...}」）。本场景置于全场景拓扑序最后：受理会真实起后台线程（本机 archify skill 缺失 → 走 npx 安装尝试或判 failed），后续无依赖场景、夹具每轮 verify.yaml prepare --reset 复位，副作用限夹具项目。响应体形状 SPEC 未约定，不臆测断言。生成完成后的 ready 落盘链路由 cli-arch-unit-tests 单测覆盖（真实 claude 分钟级不可等待）。 | pass | 0/2 | - |
