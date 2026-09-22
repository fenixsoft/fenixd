# 验证报告：add-impl-selfcheck-model-probe

> ⚠️ 本报告由框架于 2026-09-22T15:55:18Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-22T15:38:02.864678+00:00

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 20/23 场景通过，3 失败，0 错误（1 个真实产品 Bug）**

23 场景：20 pass / 3 fail。归因：product-bug 1（验证引擎断言模型丢弃空串 expected，误判 json_path 空串断言）、test-defect 2（场景文件缺陷：输出域污染、色值换算错，已原地修复）+ 同根因连带修正 1 处通过场景的色值字面量；flaky 0 / env 0。SPEC 交付面（自检 CLI 负向/修复闭环/零副作用、prompt 注入契约、unrecognized_model 分类、模板链卫生、运维文档、full-suite 读侧指纹优先级 fresh/stale/legacy/双缺四态、help 读侧与渲染）全部通过，被测产品代码无缺陷。

| 指标 | 数量 |
| --- | --- |
| 通过 | 20 |
| 失败 | 3 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 8.21M |
| 本链增量 Token（输出） | 0.10M |


## 真实产品 Bug

### BUG-01（severity=major）· json_path

- 关联场景：api-fullsuite-both-missing-pending
- 描述：验证引擎断言模型把空字符串 expected 当作缺省值丢弃：Assertion.expected 声明为 str 默认 ""（core/verify_engine/scenarios.py:832），to_dict 仅在 expected != "" 时输出该键（:850-851），场景经 from_dict→to_dict 往返后 json_path 断言的 expected="" 被丢键，运行时按 expected=None 比较（报告记录 expected:null），合法断言「detail 为空串」被确定性误判失败；且存在反向风险——路径缺失 actual=None 时 None==None 会误判通过
- 根因：Assertion dataclass 以 "" 兼作 expected 的「未设置」哨兵并与合法空串期望值冲突；应改用 None 哨兵（expected: Any = None，to_dict 以 `is not None` 判定），或 json_path 断言旁路原始 dict 不经 Assertion 往返
- 证据（场景 api-fullsuite-both-missing-pending 结构化证据，引用）：
  - failed_assertions: [{"type": "json_path", "path": "quality_gates.items[0].detail", "expected": "\"\"（场景文件原文；运行时被引擎丢弃后记录为 null）", "actual": ""}]
  - screenshots: []
  - first_failed_step: 断言3：场景文件 expected="" 与读侧空串契约一致且产品实返 ""（行为正确），失败纯因引擎把空串 expected 丢键后按 None 比较——验证引擎断言序列化缺陷（scenarios.py:832/:850），非场景亦非读侧问题


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| selfcheck-string-dispositions-rejected | 收工自证 CLI 负向路径：构造 status=success、tasks.md 全勾对齐、code_review.dispositions 为字符串数组 ["fixed","fixed"] 的结果文件夹具，运行 python3 -m core.agent_runner.result_gate --selfcheck <路径>——退出码 1、stderr 逐条违规明细含条目序号 dispositions[0] 非对象、违规计数汇总与「修复后重跑至退出码 0」收工提示（SPEC impl-result-selfcheck「字符串数组 dispositions 被自检拦截」；run_selfcheck 出处 core/agent_runner/result_gate.py:1612，条目校验体 :518 逐条 isinstance 判定，用法入口 :1660）。夹具写入 .history/（gitignore 隔离）并在场景内自清理。 | pass | 0/6 | - |
| selfcheck-fix-then-pass-loop | 收工自证修复闭环（run 内修复而非整轮重派）：同一 run 步骤内先以字符串数组 dispositions 触发自检 exit 1，随后再按 stderr 明细改写为对象数组 [{"disposition": "fixed"}, {"disposition": "deferred", "reason": "…"}] 重跑自检得 exit 0 且 stdout 打 selfcheck PASS、stderr 无违规行（SPEC impl-result-selfcheck「agent 据此在 run 内改写后重跑自检得到退出码 0」；result_gate.py:1612 run_selfcheck / :515 DISPOSITION_WHITELIST）。 | failed（已修正） | 1/3 | test-defect |
| selfcheck-valid-zero-side-effects | 自检通过零副作用：完全合法的结果文件（success + completed_tasks 与全勾 tasks.md 对齐 + 对象数组 dispositions 含 deferred 非空 reason 正例）过自检——退出码 0、stdout selfcheck PASS、stderr 无任何 selfcheck 行，且对夹具目录全部文件做 mtime/size 快照前后对比一致（除读取目标文件外零写入零网络）（SPEC impl-result-selfcheck「自检通过零副作用」；result_gate.py:1612-1657 只读语义）。 | pass | 0/5 | - |
| selfcheck-usage-and-missing-file-errors | 自检 CLI 使用错误路径：①无参数调用 python3 -m core.agent_runner.result_gate → 退出码 2 + stderr 输出完整用法提示；②--selfcheck 指向不存在文件 → 退出码 2 + stderr「结果文件不存在」+ 用法提示（SPEC impl-result-selfcheck「CLI 对缺失参数、文件不存在等使用错误 MUST 输出用法提示并以非零码退出」；result_gate.py:1660-1673 main 参数校验，:1604 _SELFHECK_USAGE）。 | pass | 0/4 | - |
| selfcheck-broken-json-fail | 自检 CLI 异常路径：结果文件为截断非法 JSON（{"status": "success", 半截）→ 自检退出码 1，stderr 含「非法 JSON」违规明细与 selfcheck FAIL 标记（基础结构校验 _check_artifact_json_file 的 JSONDecodeError 分支；result_gate.py:434-435 / :1629 第一道校验）。 | pass | 0/4 | - |
| prompt-injection-selfcheck-contract | 收尾 prompt 注入契约（impl-result-selfcheck Requirement 2）：离线构建 implementer 收尾检查注入段（PromptBuilder._selfcheck_section），断言其包含①自检 CLI 完整可执行命令（python3 -m core.agent_runner.result_gate --selfcheck <worktree>/.fenix-run-result.json）②「非零退出不得收工、按 stderr 明细修复后重跑直至退出码 0」强制措辞③dispositions 合法正例/非法反例逐字 JSON 片段④status 枚举与 completed_tasks 必填键说明（枚举/白名单取自 AgentRunner._IMPL_RESULT_STATUSES 与 result_gate.DISPOSITION_WHITELIST 单源，非本段字面量）。注入接线出处 core/agent_runner/prompt_builder.py:448-449（implementer/fast-track 收尾统一注入）、段体 :783-828。 | pass | 0/10 | - |
| prompt-injection-regression-delegation | 收尾 prompt 回归降级措辞（impl-regression-delegation Requirement 1）：离线构建质量门禁落盘契约段（PromptBuilder._quality_gates_section），断言其包含「全量回归由验证链执行」「默认不跑回归、也不写 full-suite 键」「仅当确认框架侧回归产物不可用时才在 run 内执行并落盘」「缺项零打回」降级路径措辞，且 frontend-build 条件执行与 interaction-contract 两项自查要求保持不变、gate-id 全集仍为 3 项无 code-review 键（出处 core/agent_runner/prompt_builder.py:732-781，降级措辞 :763-766）。 | pass | 0/9 | - |
| pytest-impl-selfcheck-model-probe | 单测面全量回归：运行本 SPEC 新增测试文件 tests/test_impl_selfcheck_model_probe.py（29 用例，-v --tb=short，实测输出行形已核对），覆盖①自检 CLI 同源判定与字符串数组拦截②模板链卫生③unrecognized_model 首选拒立即切链/全链拒收场归因/5xx-超时-黑洞路径不变④派发器对 [model-chain-unavailable] 归因不重派不增计数（implementer 与 fast-track 双车道）⑤full-suite 缺项零打回⑥回归快照写侧指纹 stamp 与读侧优先级。命令仅用 -v 不带 -q（PASSED 行形依赖，pytest 断言硬约束）。 | pass | 0/13 | - |
| classify-unrecognized-strict-matching | unrecognized_model 分类严格性直测（误判防线）：直接调用 ProviderCircuit.classify_unrecognized_model_error——[claude-code:unrecognized_model] 结构化标记与裸 unrecognized_model 文本命中为 True；5xx 过载/连接超时/连接拒绝/空串均 False（其余 provider 错误处理路径不变，SPEC「其他错误路径不变」）。并断言 annotate_model_chain_unavailable 注入的全链归因含 MODEL_CHAIN_UNAVAILABLE_MARKER（[model-chain-unavailable]）、「全链模型不可用」语义、provider/model 名、unrecognized_model 类别与已拒计数（出处 core/agent_runner/provider_circuit.py:269 分类器、:57 严格 pattern、:64 标记常量、:104-117 归因注入）。 | pass | 0/12 | - |
| template-chain-hygiene | 入库模板链卫生（model-chain-health-probe Requirement 2 模板侧）：.fenix/config.template.yaml 全文不含 maomaoai provider、不含被实测拒模型 deepseek-v4.1-flash 组合（file_content negate 断言双重固化），models 注释示例处含「拒模型链卫生」警示注释（提及 unrecognized_model 确定性失败语义），且模板仍可被 yaml.safe_load 解析为 dict（警示注释不得破坏模板可用性）。出处 .fenix/config.template.yaml:204-219（拒模型链卫生注释段）。 | pass | 0/8 | - |
| ops-doc-complete-and-registered | 人工运维步骤文档化（model-chain-health-probe Requirement 2 文档侧）：docs/help/13-model-chain-ops.md 含摘除理由（12 次拒模型实测）、识别信号、运行时 .fenix/config.yaml 摘除步骤、各链剩余条目 ≥3 核对项、恢复条件、以及「在 .fenix/todo.md 登记提醒」的人工指示；docs/help/README.md 完整目录表登记 #13 一行（含 13-model-chain-ops.md 链接与「模型链运维」标题）。出处 docs/help/13-model-chain-ops.md:7/:36/:40/:50、docs/help/README.md:24。 | pass | 0/10 | - |
| seed-priority-spec | 种子（夹具项目 /root/scheduling-showcase 的合成 spec sp-probe-fullsuite）：STATE.md 幂等重建 status=testing 块；写 quality-gates.json（run 内自查 full-suite passed 100/0 + frontend-build skipped 非空 reason + interaction-contract passed）；写框架侧回归产物 .fenix/regression/last-run.json（status=failed 5000/3 + 经 core.regression.current_repo_fingerprint 实时采集的当前分支指纹 stamp）——自查与产物结论刻意冲突，供读侧优先级仲裁。指纹采集与读侧同函数单源（core/regression.py:297 current_repo_fingerprint、写侧 stamp 形态 :332-347；读侧 core/dashboard/data/quality_gates.py:237）。夹具项目出处 bin/fixture_scheduling_showcase.py（历史轮同款宿主）。 | pass | 0/4 | - |
| api-help-doc-model-chain-ops | api 契约（新运维文档经 help 读侧通道可见）：①GET /api/help/doc?name=13-model-chain-ops.md → 200 且 content 含标题「模型链运维」、摘除理由节与 .fenix/todo.md 登记指示；②GET /api/help/docs → 200 且清单含 13-model-chain-ops.md 条目（README 置顶后按文件名字典序）。端点为被测交付端点打真实实例禁止 mock；HELP_DOCS_DIR 指向运行实例仓库 docs/help（core/dashboard/server.py:76-77），故该端点同时验证交付文件已被运行实例加载（出处 core/dashboard/routes/help_routes.py:58 _api_help_docs、:82 _api_help_doc）。 | pass | 0/7 | - |
| web-help-model-chain-ops | 帮助页渲染新运维文档：navigate 至帮助页并经 hash 查询参数选中 #13（#/help?doc=13-model-chain-ops.md）——左侧文档目录含「13 模型链运维」菜单项，正文区渲染出「摘除理由：12 次拒模型实测」与「在 .fenix/todo.md 登记提醒」章节。桌面布局为目录+正文同卡片（help/index.tsx:356-394），text_contains 以 body 为域全页检索。导航出处 core/dashboard/static/src/pages/help/index.tsx:29（hash 查询参数 doc 解析）、:302（menuItems 目录渲染）、:113（app.tsx /help SPA 路由）。 | pass | 0/4 | - |
| api-fullsuite-product-priority-on-conflict | api 契约（full-suite 门数据源优先级·冲突取产物）：GET /api/specs/sp-probe-fullsuite?project=scheduling-showcase——框架侧回归产物（failed，指纹匹配）与 run 内自查值（passed）同时存在且结论不一致，读侧 MUST 以产物为准：items[0] full-suite=failed、detail 可溯源（含产物路径与「分支指纹匹配」及计数「通过 5000，失败 3」）；其余门不受影响（frontend-build skipped、interaction-contract passed、框架守卫 2 项 testing 态 passed、done=4）。端点为被测交付读侧的真实服务端点，打真实实例禁止 mock（出处 core/dashboard/routes/base.py:316 /api/specs/<spec> 路由 → spec_routes.py:33 _api_spec_detail → quality_gates.py:275 _full_suite_status 双源仲裁）。 | pass | 0/11 | - |
| web-fullsuite-product-failed-rendering | 详情页渲染（产物 failed 优先呈现）：navigate 至 sp-probe-fullsuite 详情页——质量门禁 Card 可见、恒 6 道 quality-gate-item、进度条「4 / 6」、full-suite 行红色文字（#cf1322 → rgb(207, 19, 22)，qualityGates.ts gateTextColor）且辅助文案透传产物归因「框架侧回归产物 .fenix/regression/last-run.json」、「当前：全量回归测试：未通过」进展文案（quality_gates.py:375 _gates_current）。导航出处 core/dashboard/static/src/pages/projects/detail.tsx:1874（quality-gates-card 渲染）、:1890（quality-gate-item）；前端渲染语义映射 core/dashboard/static/src/pages/projects/qualityGates.ts:55-80。 | failed（已修正） | 1/7 | test-defect |
| seed-stale-product | 种子（指纹陈旧产物）：把 sp-probe-fullsuite 的 .fenix/regression/last-run.json 指纹 stamp 的 head_commit 改写为伪造陈旧值（f*40），status 仍 failed——模拟「修复轮后 HEAD 前移，产物对应旧代码」；quality-gates.json 自查值保持 passed 不变。读侧 MUST 按指纹陈旧判产物不可见并回落自查值（quality_gates.py:258-262 指纹比对分支）。 | pass | 0/2 | - |
| api-fullsuite-stale-falls-back | api 契约（指纹陈旧回落自查值）：GET /api/specs/sp-probe-fullsuite?project=scheduling-showcase——产物 failed 但指纹陈旧按不可见处理（不采信 stale 报告），full-suite 门回落 quality-gates.json 自查值 passed，detail 为自查计数「通过 100，失败 0」且不含产物溯源字样（SPEC quality-gates-progress「指纹陈旧不采信」/impl-regression-delegation 数据源优先级②；quality_gates.py:275-289 fail-open 逐级回落）。 | pass | 0/3 | - |
| seed-legacy-product-running-selfcheck | 种子（存量快照无指纹字段 + 自查 running 中间态）：改写 .fenix/regression/last-run.json 为存量形态（status=passed 200/1、删除 repo_fingerprint 字段——add-impl-selfcheck-model-probe 之前落盘的快照无分支指纹），同时把 quality-gates.json 自查 full-suite 改为 running（渐进落盘中间态）。读侧 MUST 对无指纹存量快照按不可见处理并回落自查值 running（quality_gates.py:253-255 缺指纹分支），以此与上一态（自查 passed）形成可区分观测。 | pass | 0/2 | - |
| api-fullsuite-legacy-falls-back | api 契约（存量无指纹快照不采信）：GET /api/specs/sp-probe-fullsuite?project=scheduling-showcase——框架侧产物 status=passed 但缺 repo_fingerprint 字段，读侧 MUST 按不可见处理（MUST NOT 采信存量 passed 压过自查值），full-suite 门呈现自查值 running（观测区分点：若误采信存量快照则会呈现 passed，断言即红）。 | pass | 0/2 | - |
| seed-both-missing | 种子（双源皆无·新契约默认形态）：删除 .fenix/regression/last-run.json（收尾不残留合成回归快照），并把 quality-gates.json 重写为仅 frontend-build（skipped 非空 reason）+ interaction-contract（passed）两项、无 full-suite 键——即 implementer 按新契约「默认不跑回归也不写 full-suite 键」的标准落盘形态（prompt_builder.py:763-766 降级措辞对应物）。收尾后夹具项目不残留合成回归快照。 | pass | 0/3 | - |
| api-fullsuite-both-missing-pending | api 契约（双源皆无呈现 pending 零打回）：GET /api/specs/sp-probe-fullsuite?project=scheduling-showcase——既无框架侧回归产物、quality-gates.json 亦无 full-suite 键：items[0] full-suite=pending 且 detail 空、不抛异常、不影响其余 5 道门（frontend-build skipped / interaction-contract passed / testing 态框架守卫 2 项 passed）、done=4 total=6（SPEC quality-gates-progress「双源皆无呈现 pending 零打回」；quality_gates.py:285-289 回落 _run_gate_status 键缺 → pending）。 | failed（已修正） | 1/9 | product-bug |
| web-fullsuite-both-missing-pending | 详情页渲染（缺项 pending 零打回呈现）：navigate 至 sp-probe-fullsuite 详情页——质量门禁 Card 可见、恒 6 道、进度条「4 / 6」（pending 不计入 done 但其余门不受影响）、页内无任何红色 failed 行（rgb(207, 19, 22) 元素不存在=缺项零打回的 UI 呈现）、pending 项灰色（rgb(153, 153, 153)）可见。导航出处 core/dashboard/static/src/pages/projects/detail.tsx:1874/:1890；渲染语义 qualityGates.ts:55-66（failed 红/pending 灰）。 | pass | 0/6 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| selfcheck-fix-then-pass-loop | output_match[stream=stderr, negate] 不含 "selfcheck FAIL" | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景步骤 sys.stderr.write(r.stderr) 将阶段1 stderr 一并写入输出域，negate 断言扫全量 stderr 必命中阶段1 的 selfcheck FAIL 行；exit_code=0 与 combined 含 selfcheck PASS 证明阶段2 产品行为正确，属场景输出域... |
| web-fullsuite-product-failed-rendering | element_visible span[style*='rgb(207, 19, 22)'] full-suite 行红色 failed 文字 | test-defect | 测试用例自身缺陷（非产品缺陷） | pending 兄弟场景灰 span rgb(153,153,153) 内联样式断言可过，门禁行渲染机制在场；失败态文案均渲染（框架侧回归产物…/当前：全量回归测试：未通过），唯 rgb(207, 19, 22) span 不存在——待源码核对 gateTextColor failed 落点与实际着色机制后定谳 |

## 本轮场景集变更

场景集与持久化集一致，无变更。

