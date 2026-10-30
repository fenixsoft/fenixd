# 验证报告：dsh-primary-acceptance-switch

> ⚠️ 本报告由框架于 2026-10-13T15:41:00Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-13T15:40:59.755140+00:00+run-result@mtime1791906059801134196

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 7.17M |
| 本链增量 Token（输出） | 0.12M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| dsh-acceptance-fixture-mode | 一键验收脚本 fixture 模式：无参执行即生成玩具项目夹具（临时目录+唯一前缀+最小 SPEC 种子），正常退出且输出给出夹具路径（/tmp 下），全程不依赖任何 dsh 凭据。（出处：spec/changes/dsh-primary-acceptance-switch/tasks.md 1.1；bin/dsh_acceptance.py 为本 SPEC 新增交付物） | pass | 0/2 | - |
| dsh-acceptance-smoke-multilane | 一键验收脚本 smoke 模式：无凭据可重复的假端点全链冒烟，覆盖 ≥3 车道（implementer/verifier/经 run_one_shot 的监督 judge），各车道终态/在飞判定/产物硬门全链正确；收集 run jsonl/投影计数/.fenix-run-result.json/run_metrics 证据，退出时清理玩具项目与 runs 产物（唯一前缀识别，含手工清理兜底命令入 runbook）；失败 fail-loud 非零退出、不出假绿报告——成功判据即退出码 0。起点提示：SPEC-3 的 tests/test_dsh_e2e_smoke.py 当前在本仓环境报 dsh 启动 Missing services（fenixModelConfig 缺失连锁：headless-runner←agentDefaultModel←fenixModelConfig），smoke 的 DSH_HOME profile 装配须解决该缺口（design 决策 4：根源在 SPEC-2/3 交付物的缺陷回归本分支修复）。环境依赖（有 fallback: 脚本自带 DSH_HOME 隔离与 mock-model-server.mjs 假端点自装配，无凭据可重复；依赖本机已装的 dsh 0.2.0-rc.2 与 node 二进制）。（出处：tasks.md 1.1/1.2/1.3/2.1；specs/dsh-primary-acceptance/spec.md「一键验收脚本」） | pass | 0/1 | - |
| dsh-acceptance-accept-nocred | 真实模式执行前自检（无凭据环境）：先准备空 DSH_HOME，再以清空的凭据环境变量（ANTHROPIC_API_KEY/ANTHROPIC_BASE_URL/FENIX_DSH_PROVIDER_API_KEY 置空串）执行 accept——自检失败、列出缺失项与修复指引（输出含「缺失」），按 fail-loud 惯例非零退出（断言退出码 1），且不发起任何真实模型调用。（出处：specs/dsh-primary-acceptance/spec.md「真实模式执行前自检」Scenario；core/agent_runner/harness/dsh_adapter.py:77-79 凭据桥接变量名 FENIX_DSH_PROVIDER_API_KEY） | pass | 0/2 | - |
| dsh-regression-existing-lanes | 回归保护：本 SPEC 不改 core 缺省值与任何车道行为——既有 harness 适配层/投影/全链（stub）测试套全绿。planner 实测当前基线 114 passed（projection/harness_config/harness_dsh_adapter/harness_adapter/dsh_full_chain 五文件，纯 stub 不依赖真实 dsh，3.7s）。判定自身车道缺陷是否被本分支改动破坏。（出处：proposal.md Impact「不改 core 缺省值与任何车道行为」；tests/test_dsh_full_chain.py:1-15 stub 形态）（三轮裁决原地修复：套内 test_heat_reload_new_value_applies_next_dispatch 非密封——首派发拦截断言依赖环境无健康 dsh 前提，本机 dsh 0.2.0-rc.2 已装且 profile 已挂致真实 check_health 通过、首派发直通 inner 而失配。场景文件缺陷=夹具未自建：补步骤1 shim 夹具（/tmp/dsh-reg-shim/dsh 必然 exit 9→HarnessHealthError）并在 pytest 步 PATH 前插该目录，使套件文档化前提「纯 stub 不依赖真实 dsh」确定性自建；断言两条未弱化未删除，实测 114 passed/exit 0） | pass | 0/2 | - |
| dsh-default-harness-unchanged | 缺省值不翻转回归：ConfigLoader.get_harness 对空配置仍回缺省 claude（proposal BREAKING: 无——默认值是否翻转由用户依据验收报告裁决，翻转本身属后续一次性微变更，不在本 SPEC）。进程内单源探针，零网络零副作用。（出处：core/config.py:317 HARNESS_DEFAULT="claude"、:320 get_harness；proposal.md What Changes） | pass | 0/2 | - |
| dsh-runbook-sections | 运行手册关键章节齐备（文件级）：docs/help/dsh-harness-runbook.md 逐关键词 grep 锚定 SPEC 锁定内容——切换步骤（agent.harness）、回切步骤（回切）、故障处置四类（版本漂移/429/投影/健康检查）、夹具手工清理兜底命令（清理）。关键词全部取自 SPEC/tasks 字面词，不臆测行文；任一缺失grep 链即非零失败。（出处：tasks.md 3.1/1.3；specs/dsh-primary-acceptance/spec.md「切换与回切运行手册」；core/dashboard/server.py:76 HELP_DOCS_DIR=FRAMEWORK_ROOT/docs/help） | pass | 0/1 | - |
| dsh-runbook-report-template | 验收报告模板齐备（文件级）：runbook 内嵌报告模板含五段证据关键词（各车道终态→终态；投影计数与坏事件统计→坏事件；usage 降级情况→usage；耗时对比 claude 基线→claude；产物硬门结果→硬门）与「默认值是否翻转 claude→dsh」决策申请段（默认值），并含 ADR-271、母设计文档（multi-harness-adapter-design）、上游 SPEC（add-dsh-adapter-integration）交叉引用。（出处：tasks.md 3.2/3.3；specs/dsh-primary-acceptance/spec.md「切换与回切运行手册」报告模板条款） | pass | 0/1 | - |
| dsh-todo-signal-entry | 真实验收信号落位：.fenix/todo.md（git 跟踪文件）含真实验收执行请求——执行命令引用本 SPEC 交付的 bin/dsh_acceptance.py（grep 'dsh_acceptance'）并写明前置条件（grep '前置条件'）。信号式交付范式：agent 落位+预演自检，实际真实验收由用户发起，默认值翻转决策不在任何自动化路径。（出处：tasks.md 4.1；specs/dsh-primary-acceptance/spec.md「请求落位且预演通过」；design.md 决策 2 restart_request 信号范式） | pass | 0/1 | - |
| dsh-runbook-help-docs-api | 帮助中心文档清单 API 收录运行手册：GET /api/help/docs（docs/help/ 动态读盘，FRAMEWORK_ROOT 相对验证树）返回 200 且清单含 dsh-harness-runbook.md（ASCII 文件名子串断言，免疫中文 ensure_ascii 转义）。（出处：core/dashboard/routes/help_routes.py:59-88 _api_help_docs；core/dashboard/server.py:76-82 HELP_DOCS_DIR/HELP_DOC_NAME_RE） | pass | 0/2 | - |
| dsh-runbook-help-doc-api | 帮助中心单篇文档 API 可取运行手册全文：GET /api/help/doc?name=dsh-harness-runbook.md 返回 200 且响应体含「agent.harness」（切换步骤的配置键，ASCII 子串断言；缺文件时该端点按 404 语义失败即场景失败）。（出处：core/dashboard/routes/help_routes.py:90-137 _api_help_doc；core/dashboard/server.py:79 HELP_DOC_NAME_RE 白名单） | pass | 0/2 | - |
| dsh-runbook-help-page | 帮助页面渲染运行手册（裁决原地修复：原 navigate /help#/?doc=... 直达依赖服务端 SPA history fallback，实测 GET /help 404 而 GET / 200——server.py 无 /help 直达路由，属场景臆测能力，改站内导航：根路径载入 SPA → 点侧边菜单「帮助」进帮助页 → 点文档目录中运行手册条目（setDocInUrl 写 hash、hashchange 触发 getDocFromUrl 重拉））。左侧文档目录渲染、运行手册条目呈选中态（.help-menu-item.active——证明非回退到缺省 README.md），正文区含「agent.harness」文本；页面无控制台错误。断言四条全保留未弱化。（出处：core/dashboard/static/src/app.tsx:135 /help 菜单项；core/dashboard/static/src/pages/help/index.tsx:33-45 getDocFromUrl/setDocInUrl、:293-299 .help-menu/.help-menu-item、:363 hashchange 监听；core/dashboard/static/src/pages/help/help.css:33 .active）（二轮裁决原地修复：目录条目渲染文本是文档标题 {d.title}（index.tsx:310）而非文件名，原 :has-text("dsh-harness-runbook") 锚渲染文本必失配——改锚标题子串「运行手册」，docs/help/ 全目录唯一命中，断言四条未动） | pass | 0/4 | - |
| dsh-acceptance-unit-tests | 脚本单元测试全绿：tests/test_dsh_acceptance.py 覆盖三模式行为、证据收集与判定逻辑、夹具清理无残留、fail-loud 路径。命令只 -v 不带 -q（pytest 9 中 -q 覆盖 -v 会吞 PASSED 行）；断言只锚 pytest 汇总行「 passed」子串与退出码，不臆测具体用例名。环境依赖（有 fallback: 测试内自装 stub 与假端点；依赖 dsh/node 二进制在场，缺失时由测试自身skip 语义兜底）。（出处：tasks.md 2.2） | pass | 0/2 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

