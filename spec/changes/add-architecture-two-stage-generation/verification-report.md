# 验证报告：add-architecture-two-stage-generation

> ⚠️ 本报告由框架于 2026-09-26T04:53:39Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-26T04:53:39.728580+00:00

## 结论：✅ 通过（verified）

**状态：verified — 21/21 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 21/21 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 21 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.51M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-arch-two-stage-unit-tests | 两段式管线全量单元测试：pytest 运行 tests/test_dashboard_architecture_api.py（30 例，tasks 3.1/3.2 规定覆盖：HEAD 一致跳过阶段1 / HEAD 变化重探索 / 阶段1 非零退出与 evidence 缺失·空文件短路 / 阶段1·阶段2 分段超时进程组击杀 / stage 字段两段取值与终态 null / 双段 prompt 绝对路径引用不内嵌全文 / 单飞 409 / 产物判定链），并逐条断言本 SPEC 新增用例的真实 PASSED 输出行（-v 形态，无 -q 覆盖；本文件无 parametrize，用例名无后缀）。 | pass | 0/13 | - |
| cli-arch-two-stage-prompt-contract | 双段 prompt 构建器契约直检（tasks 1.1/1.2）：经 importlib 直载 core/dashboard/routes/architecture_routes.py（纯 stdlib 模块零包副作用），断言阶段1 探索 prompt 含 ARCHIFY_EVIDENCE_DONE marker 与 evidence.md 写盘绝对路径、不含 SKILL.md 字样（不注入 skill 全文）、长度 <2048 字节（小上下文安全区）；阶段2 出图 prompt 含 vendor/archify/SKILL.md 绝对路径引用、evidence.md 绝对路径、分段小步写纪律（逐段/禁止单次巨量）、ARCHIFY_DONE marker，且长度 <4096 而 SKILL.md 实际 >8000 字节（结构上不可能内嵌全文，另取 SKILL.md 真实行探针确认不内嵌）；分段超时常数 _EXPLORE_TIMEOUT_SECONDS==720 / _AUTHOR_TIMEOUT_SECONDS==1080（architecture_routes.py:48-49）；_status_payload 恒含第 7 键 stage 且缺省 null（architecture_routes.py:279-300）。 | pass | 0/2 | - |
| cli-arch-head-fingerprint-helpers | evidence HEAD 指纹 helper 生命周期直检（tasks 1.3）：临时 git 仓库上实测 _stamp_evidence_head 写入 evidence-head: <sha> 头部、_evidence_head_matches HEAD 一致判可复用；第二次 commit 后 HEAD 变化判不匹配（自动重探索）；无指纹头判不匹配；二进制损坏字节判不匹配；非 git 项目取不到 HEAD 判不匹配（design D2：缺失/损坏/无指纹头/取不到 HEAD 一律重探索，architecture_routes.py:194-266）。 | pass | 0/2 | - |
| cli-arch-clean-fixture | 清理夹具项目 scheduling-showcase 的架构产物目录 /root/scheduling-showcase/.fenix/architecture/（status.json/diagram.html/evidence.md 三件运行时产物族，architecture_routes.py:66-69），为「从未生成 none」各场景提供确定性初态（对齐 add-project-architecture-tab cli-seed-clean-arch 已验收先例；夹具由 verify.yaml prepare 每轮幂等供给）。 | pass | 0/2 | - |
| api-arch-status-unknown-project-404 | 未注册项目 GET /api/architecture/status?project=no-such-project-2stage → 404 project not found（architecture_routes.py:768-771，两段式改造不改变项目存在性守卫）。 | pass | 0/2 | - |
| api-arch-status-none-schema | 从未生成态 GET /api/architecture/status?project=scheduling-showcase → 200 且 state==none，响应含全量 8 键契约（project + 存量六键 + 新增可选键 stage，architecture_routes.py:279-300/774），stage 为显式 null（none 态无阶段语义；引擎 exact 模式区分显式 null 与路径缺失，0 误判）。 | pass | 0/4 | - |
| api-arch-diagram-not-generated | state=none 时 GET /api/architecture/diagram?project=scheduling-showcase → 404 结构化错误且 code==architecture_not_generated（architecture_routes.py:808-814：state!=ready 走稳定 code 分支，两段式改造后判定链入口不变）。 | pass | 0/3 | - |
| web-arch-none-empty-state | 从未生成空态渲染（回归：前端不改，四态机消费新后端响应形态）：?tab=architecture 直开未生成项目，「项目架构」页签可见、空态文案「尚未生成架构图」可见、「刷新架构图」按钮可见、不渲染 iframe（ArchitectureTab.tsx:163-178 none 态分支；页签挂载 list.tsx:1430-1436；SPA hash 路由 /projects 出自 core/dashboard/static/src/app.tsx:125 路由表）。不点击按钮（会真实 spawn 分钟级生成，触发链路由 api-arch-refresh-two-stage-live 承担）。 | pass | 0/5 | - |
| cli-arch-seed-ready-old-format | 向夹具项目写入「旧版六键格式」就绪态种子（无 stage 键，模拟两段式上线前的存量 status.json）：state=ready + component_count=12 + diagram.html（含独特标记 ARCH-2STAGE-DIAGRAM-MARKER 的自包含 HTML），供「读侧容忍缺键」向后兼容 MUST（design D5：读侧容忍缺键/多键）的确定性验证。依赖 none 态三场景消费完毕后覆写。 | pass | 0/2 | - |
| api-arch-status-old-format-tolerated | 旧版六键 status.json 读侧容忍（design D5 向后兼容 MUST）：GET status → 200 且 state==ready、存量六键齐全（json_schema 必需集不含 stage），读侧补齐逻辑不因缺 stage 键报错（architecture_routes.py:449-455 逐键补齐：full 以七键缺省起底、仅覆盖 data 中存在的键）。 | pass | 0/4 | - |
| cli-arch-seed-ready-new-format | 向夹具项目覆写「新版七键格式」就绪态种子（stage 显式 null + 存量六键，architecture_routes.py:292-300 终态形态）：state=ready + component_count=12 + generated_at 种子值 + diagram.html（自包含 HTML 含 ARCH-2STAGE-DIAGRAM-MARKER），供 ready 态 api/web 场景确定性驱动。 | pass | 0/2 | - |
| api-arch-status-ready-stage-null | 就绪态（新七键格式）GET status → 200 且 state==ready、component_count==12（种子值，落在 8–16 合法区间）、stage 显式 null（终态 stage 置 null 契约，spec「stage 字段写入」：终态时该键置 null；引擎 exact 模式断言显式 null）。 | pass | 0/5 | - |
| api-arch-diagram-ready-served | 就绪态 GET /api/architecture/diagram → 200 下发 diagram.html，Content-Type 含 text/html、响应体含种子标记 ARCH-2STAGE-DIAGRAM-MARKER（architecture_routes.py:815-817 state==ready 分支；两段式改造后阶段2 产物判定链与下发路径不变，回归点）。 | pass | 0/3 | - |
| web-arch-ready-iframe-sandbox | 就绪态沙箱渲染（回归：前端不改）：?tab=architecture 直开种子 ready 项目，断言 iframe[sandbox="allow-scripts"] 可见（不带 allow-same-origin）、「生成时间：」元信息区可见（ArchitectureTab.tsx:234-249 ready 态元信息 + iframe key=generated_at）、刷新按钮仍可见可点。后端响应多出的 stage 键不影响渲染（向前兼容回归）。 | pass | 0/5 | - |
| cli-arch-seed-failed-with-stage | 向夹具项目覆写「失败态（新七键格式）」种子：state=failed + error 含独特标记 SEED-2STAGE-FAIL-01 + stage 显式 null + component_count=null（终态形态 architecture_routes.py:292-300），供 failed 态 api/web 场景确定性驱动。依赖 ready 态场景消费完毕后覆写。 | pass | 0/2 | - |
| api-arch-status-failed-stage-null | 失败态 GET status → 200 且 state==failed、error 含种子标记 SEED-2STAGE-FAIL-01（读侧 verbatim 回传失败原因）、stage 显式 null（失败终态 stage 置 null；_finish 终态落盘不带 stage → payload stage=None，architecture_routes.py:721-746）。 | pass | 0/4 | - |
| web-arch-failed-error-retryable | 失败态渲染与可重试（回归：前端不改）：?tab=architecture 直开种子 failed 项目，断言错误信息渲染（text_contains 种子标记 SEED-2STAGE-FAIL-01——用自种标记做 verbatim 断言避免词表幻觉）、「刷新架构图」按钮恢复可点（element_enabled，重试入口）、不渲染 iframe（ArchitectureTab.tsx:198-210 failed 态分支）。 | pass | 0/5 | - |
| cli-arch-seed-generating-residue-stage | 向夹具项目覆写「重启残留（带 stage 键）」种子：state=generating + stage=exploring + started_at=2 小时前（模拟两段式上线后 daemon 重启杀掉在飞探索 run 的残留文件），供「读侧合成中断 failed 且 stage 归 null」的确定性验证（验证实例内存无在飞线程/进程 → status() 走合成路径 architecture_routes.py:441-448）。依赖 failed 态场景消费完毕后覆写。 | pass | 0/2 | - |
| api-arch-residue-stage-synthesis | 残留 generating+stage 合成中断（无死态 MUST，两段式新形态下的回归）：GET status → 200 且 state==failed（合成「生成被中断」）、error 含「中断」字样、stage 显式 null（合成终态 _status_payload(\"failed\", started_at=...) 不带 stage → null，architecture_routes.py:443-448）——残留 stage=exploring 键不得泄漏为非终态阶段。 | pass | 0/4 | - |
| cli-arch-seed-stale-evidence | 向夹具项目写入「HEAD 指纹不一致」的 evidence.md 种子（首行 evidence-head: 0000000000000000000000000000000000000000 \| 过去时间戳 + 非空取证正文），并清掉残留 status.json：POST refresh 受理后 _evidence_head_matches 因 sha 不一致判不匹配 → 正常执行阶段1 探索（stage=exploring），供「HEAD 变化自动重探索」（spec ADDED Requirement）的真实管线 E2E 前置。依赖合成场景消费完毕后落盘。 | pass | 0/2 | - |
| api-arch-refresh-two-stage-live | 真实两段式管线活性 E2E（本 SPEC 核心可观察行为，全场景图汇点）：POST /api/architecture/refresh?project=scheduling-showcase 异步受理（200 + ok==true + latency_under 5000ms，HTTP 线程不同步等待，architecture_routes.py:776-794）；evidence 为 stale 指纹 → 阶段1 探索 run 真实 spawn，_write_stage 先于 spawn 落盘 {state: generating, stage: exploring}（architecture_routes.py:656）——连续三次 GET status 轮询，末次断言 state==generating 且 stage==exploring（新 stage 键经真实生成在飞期可见，spec「stage 字段写入」）。真实 claude 探索为分钟级长任务，场景不等待其终态（终态判定由单元测试 fake spawn 覆盖）。 | pass | 0/6 | - |

## 本轮场景集变更

当前稳定场景集共 21 个（第 1 轮）。

- 首轮写入 21 个场景

