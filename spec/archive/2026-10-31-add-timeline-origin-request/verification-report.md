# 验证报告：add-timeline-origin-request

> ⚠️ 本报告由框架于 2026-10-28T09:49:49Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-28T09:49:48.521024+00:00+run-result@mtime1793180988578811183

## 结论：✅ 通过（verified）

**状态：verified — 18/18 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 18/18 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 18 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.47M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| fixture-origin-req-provision | 夹具供给：重建 /tmp/origin-req-verify-proj 项目（8 个 SPEC 覆盖 timeline-origin-request 全部分支：有 request.md+运行节点打断折叠 / fast-track 折叠链 / 无 request.md 存量 / 空白 request.md / request.md 为目录（读异常）/ 超长 request.md / 仅 run 无 state 节点 / 归档形态 STATE.archive.md+spec/archive/2026-10-27-*），伪造 Transition 日志（.fenix/logs/fenixd.log，与 timeline.py:293 正则同构）与 run 产物（.fenix/runs/impl-<spec>-<epoch>.jsonl），以 fixture=True 经 core/dashboard/registry.py:476 Registry.add_project 注册并对运行实例轮询 /api/projects 确认可见（projects() TTL 缓存，core/dashboard/http_server.py:76） | pass | 0/2 | - |
| cli-skill-request-md-step | 写侧契约（tasks 1.1）：skills/fenix-new/SKILL.md 存在「写立项原话」子步骤——request.md 写入命令模板（cat > spec/changes/<name>/request.md）、原文照录不做工程化改写纪律、--modify 不更新纪律、request.md 不入 Deliverables 声明 | pass | 0/2 | - |
| cli-timeline-origin-backend-tests | 读侧回归（tasks 2.2/2.3）：新增 tests/test_spec_timeline_origin_request.py 七类场景全过 + 既有时间轴隔离套件 tests/test_spec_timeline_name_isolation.py 零回归 | pass | 0/2 | - |
| cli-timeline-origin-frontend-tests | 前端渲染回归（tasks 3.3/4.2）：core/dashboard/static/tests/specTimelineOriginRequest.test.mjs 引用块渲染用例全过（携带字段渲染/缺失与空串不渲染/仅首节点/折叠链/run 节点不受影响） | pass | 0/3 | - |
| api-origin-full-first-node | 有 request.md 的 SPEC：GET /api/specs/<spec>?project=（core/dashboard/routes/base.py:719）时间轴排序+折叠后首个 state 节点（drafted→reviewing，运行节点夹在两转移间打断折叠）携带 origin_request 且值=request.md 全文（含换行的原文照录）；其余 state 节点（折叠链）与 run 节点不携带——spec.md「有 request.md 的 SPEC 首个状态节点附原话」 | pass | 0/9 | - |
| api-origin-fast-chain | fast-track SPEC（无 drafted→reviewing 转移）：drafted→ready 与 ready→implementing 连续前向折叠为单条 chain 节点，origin_request 附在该折叠链节点上、时间轴恰一条节点——spec.md「无 drafted→reviewing 转移的 SPEC 同样展示」+「折叠链首节点同样附着」（timeline.py:536 首个 state 节点即折叠链） | pass | 0/7 | - |
| api-origin-arch-reachable | 归档 SPEC（条目在 .fenix/STATE.archive.md、目录在 spec/archive/2026-10-27-origin-arch-spec）：详情接口经归档清单回退（spec_routes.py:24）进 spec_detail，resolve_spec_dir 归档路径解析读到 request.md，首个 state 节点携带 origin_request、接口零报错——spec.md「归档路径解析」+「归档时随目录整体迁移」 | pass | 0/5 | - |
| api-origin-bare-absent | 存量 SPEC（spec 目录存在但无 request.md）：时间轴 state 节点不携带 origin_request、详情接口 200 零报错（fail-open 静默省字段，timeline.py:537-544）——spec.md「无 request.md 静默降级」 | pass | 0/3 | - |
| api-origin-empty-absent | request.md 内容 strip 后为空（纯空白字符）：与缺失同口径静默省字段、state 节点照常、接口零报错——spec.md「静默降级」的空白文件分支（timeline.py:541 origin.strip() 守卫） | pass | 0/3 | - |
| api-origin-baddir-failopen | request.md 为目录（read_text 抛 IsADirectoryError 的读异常形态）：异常被吞、静默省字段、state 节点照常返回、接口 200 零报错——spec.md「读取异常同样静默省字段」（timeline.py:543 except Exception fail-open 分支） | pass | 0/3 | - |
| api-origin-runonly-no-state | 有非空 request.md 但时间轴排序折叠后不含任何 state 节点（日志窗口无该 SPEC 的 Transition，仅 run 节点）：任何节点（含 run）不携带 origin_request、接口零报错，MUST NOT 退化挂到 run 等其它 kind 节点（timeline.py:536 first_state 守卫）——spec.md「时间轴无 state 节点时不附着」 | pass | 0/3 | - |
| api-origin-long-untruncated | 超长 request.md（约 2.9KB 异常数据，30+ 行）：存储层不截断——origin_request 同时含首行标记 ORIGIN-HEAD-MARKER 与末行标记 ORIGIN-LASTLINE-MARKER（design D3「存储不截断，展示层兜底」） | pass | 0/4 | - |
| web-origin-full-quote-visible | SPEC 详情页「运行时间轴」（首个默认激活页签）首个 state 节点下渲染立项原话引用块（.spec-origin-request-quote，core/dashboard/static/src/pages/projects/components/SpecTimeline.tsx:155-172）：引用块可见、多行原文两行均在、全页恰一个引用块、状态转移卡片照常渲染。navigate 出处：SPA 详情路由 /projects/:name/:spec（core/dashboard/static/config/routes.ts:39，hash 路由） | pass | 0/6 | - |
| web-origin-fast-chain-quote | fast-track SPEC 详情页：折叠链节点（草稿→就绪→实现中 全链展开）下同样渲染原话引用块，全页恰一个——spec.md「前端渲染原话引用块」的链上节点分支 | pass | 0/5 | - |
| web-origin-arch-quote | 归档 SPEC 详情页（条目经归档清单回退进详情）：原话引用块可见且内容为归档目录 request.md 原文——归档路径可达的端到端 UI 验证 | pass | 0/4 | - |
| web-origin-bare-no-quote | 存量 SPEC（无 request.md）详情页：不渲染任何引用块结构（element_not_exist），时间轴状态转移卡片照常渲染、零控制台错误——spec.md「字段缺失不渲染任何占位」 | pass | 0/4 | - |
| web-origin-long-quote-full-text | 超长 request.md 详情页：引用块完整渲染原文首尾标记（容器 max-height+overflow:auto 滚动兜底、DOM 全文不截断，design D3），全页恰一个引用块 | pass | 0/5 | - |
| web-origin-switch-clears-quote | 交互回归：从有原话的 SPEC 经顶栏「切换 SPEC」下拉切到无 request.md 的 SPEC（core/dashboard/static/src/pages/projects/detail.tsx:893 Dropdown + :844 history.push），引用块随详情数据切换消失、时间轴照常；交互触发 /api/specs/<spec>?project= 重拉（core/dashboard/static/src/services/dashboard.ts:1164）——「字段缺失不渲染任何占位」的会话内回归点 | pass | 0/5 | - |

## 本轮场景集变更

当前稳定场景集共 18 个（第 1 轮）。

- 首轮写入 18 个场景

