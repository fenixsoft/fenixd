# 验证报告：add-code-review-auto-fix

> ⚠️ 本报告由框架于 2026-09-22T06:44:51Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-22T06:09:06.071461+00:00

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 26/31 场景通过，5 失败，0 错误（1 个真实产品 Bug）**

31 场景 26 过 5 败。败因：1 个 product-bug（config.template.yaml 缺 code-fix 模型分配示例，spec code-fix-agent MUST 项）+ 4 个场景文件缺陷（未知前缀示例选错、api 断言未绑 response、web 复原先于断言），均已原地修复待重执行。no_console_error/no_auth_error 特判无涉及。

| 指标 | 数量 |
| --- | --- |
| 通过 | 26 |
| 失败 | 5 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 30.09M |
| 本链增量 Token（输出） | 0.21M |


## 真实产品 Bug

### BUG-01（severity=minor）· json_output

- 关联场景：cli-template-and-docs-sync
- 描述：配置模板缺 code-fix 模型分配示例：spec code-fix-agent/spec.md:10 MUST 要求 .fenix/config.template.yaml 的 agents.models 含 code-fix 分配示例，实现遗漏（158 行角色清单仅 8 角色无 code-fix，models 注释块全文无 code-fix）。运行时无影响（模型链回退 code-review 已由 cli-model-chain-fallback-and-override 验证通过），属交付物文档缺口。
- 根因：implementer 未同步更新 .fenix/config.template.yaml 的 agents.models 说明块（需在角色可选清单追加 code-fix 并补一段分配示例，形态同 code-review）
- 证据（场景 cli-template-and-docs-sync 结构化证据，引用）：
  - failed_assertions: [{"type": "json_output", "selector": "models_has_code_fix", "expected": "True", "actual": "False"}]
  - screenshots: []
  - first_failed_step: 步骤1(td) json_output path=models_has_code_fix：config.template.yaml「按 Agent 角色分配模型」块（158 行角色清单仅 implementer|planner-plan|planner-judge|verifier|administrator|self-review|fast-track|code-review）全块检索无 code-fix


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-agent-registration-points | code-fix agent 四处注册点齐全：AGENT_PROMPT_FILES 含 code-fix→code-fix.md、RUN_ID_AGENT_PREFIXES 含 ("code-fix-","code-fix")、KNOWN_AGENT_TYPES 含 code-fix、框架根 agents/code-fix.md 存在且含「仅处理注入清单」与禁 merge-back/台账约束（spec code-fix-agent「code-fix agent 类型注册」；出处 core/agent_runner/prompt_builder.py:40、core/agent_runner/run_files.py:37、core/config.py:136、agents/code-fix.md:11）。 | pass | 0/10 | - |
| cli-run-id-prefix-attribution | run_id 前缀归属：infer_run_agent_type("code-fix-1758211200")→("code-fix","1758211200")；code-review-100 归 code-review、code-fix-100 归 code-fix 不互相错配；未知前缀回退泛型 ("agent", run_id)（spec code-fix-agent「run_id 前缀被正确归属」「前缀无子串冲突」；出处 core/agent_runner/run_files.py:48-56）。 | failed（已修正） | 1/5 | test-defect |
| cli-config-reader-defaults | get_code_review_fix_config 读取器：段缺失/非 dict 回退 {enabled:False,batch_size:20}；batch_size 为 0/-3/true/"20" 回退 20；enabled 非 bool 回退 False；合法 {true,30} 透传（spec code-fix-config「配置读取」；出处 core/config.py:1348-1375）。 | pass | 0/11 | - |
| cli-config-managed-keys-and-validation | Dashboard 受管键接线与写校验：_SOURCE_KEYS 含 admin.code_review_fix；_SYNC_PAGE_KEYS[quality] 含 {admin:[code_review_fix]}；write_config 拒绝 batch_size=0（报 must be a positive integer、不半写）、拒绝 enabled 非 bool；写入 {enabled:true,batch_size:30} 后 read_config 回显且 sources 标注 project（spec code-fix-config「Dashboard 受管键读写」；出处 core/dashboard/data/config_admin.py:76、175、1229-1240、1848-1857）。 | pass | 0/12 | - |
| cli-template-and-docs-sync | 配置模板与文档同步：.fenix/config.template.yaml 含整段注释形态的 code_review_fix 示例（enabled: false / batch_size: 20，且无未注释活配置）；docs/help/09-config.md 含 admin.code_review_fix.enabled 与 batch_size 映射行及专节（spec code-fix-config「配置模板与文档」；出处 .fenix/config.template.yaml:352-364、docs/help/09-config.md:306、489）。 | failed（已修正） | 1/10 | product-bug |
| cli-model-chain-fallback-and-override | code-fix run 模型链：仅配 agents.models.code-review 时 run_code_fix 子进程 env 用 code-review 的 provider(baseurl)/model（缺省同源）；显式配 code-fix 时用 code-fix 分配不被覆盖（spec code-fix-agent「模型链复用 code-review 的 LLM 配置」；出处 core/agent_runner/maintenance_runs.py:1281-1291）。 | pass | 0/7 | - |
| cli-run-code-fix-artifact-gate | code-fix run 产物硬门与计数：注入清单非空而 out 文件缺失 → success=False 且文案含「产物缺失」；out 含 1 fixed+1 skipped → success=True 且 fixed=1 skipped=2 计数正确（另一变体全 skipped → fixed=0）；损坏行不计入（spec code-fix-agent「产物缺失判失败」「逐条增量落盘」；出处 core/agent_runner/maintenance_runs.py:1190-1207、1319-1330）。 | pass | 0/9 | - |
| cli-checkpoint-guard-chain | 编排检查点守卫链与链身份：enabled 缺省→disabled 且不写进度；在飞 code-fix- 前缀 run→already_running；无 open 条目→no_open_items；45 条 open+batch_size 20→triggered 且 ctx 批=20 条、进度 total=45 batch_no=1；再投递（running=true 且 activation_id 未变）→第 2 批 ctx 且 total 仍 45 不重算（spec code-fix-lane「幂等与单飞」「批次编排循环」+ code-fix-progress「自动修复进度结构」；出处 core/code_fix.py:436-465、491-526、572-596）。 | pass | 0/20 | - |
| cli-checkpoint-regression-contract-failclosed | 回归契约缺失分流 fail-closed：verify.yaml 整体缺失→verify_contract_missing 信号+进度 blocked/regression_contract_missing；仅缺 regression 段→verify_regression_missing 信号（MUST NOT 误写 verify_contract_missing）+blocked/regression_section_missing；补上 regression 段后下一检查点自动续做 triggered（spec code-fix-lane「回归契约缺失时 fail-closed 并复用 AI 起草」；出处 core/code_fix.py:328-378、517-547）。 | pass | 0/11 | - |
| cli-batch-worker-no-effective-fix | 零有效修复拒合回：批产物行全部 skipped（且分支零提交）、回归 passed → MUST NOT 合回、MUST NOT 置 resolved，进度 phase=failed/reason=no_effective_fix，worktree 被 cleanup 失败态释放，台账条目保持 open（spec code-fix-lane「零有效修复拒合回」；出处 core/code_fix.py:782-803）。 | pass | 0/7 | - |
| cli-batch-worker-regression-fail-discard | 两次回归均失败丢弃：不合回、不置 resolved、条目保持 open、保留 worktree 不 cleanup、写 code_fix_regression_failed 告警信号、失败批保留集合落 fix-failed.json、todo.md 追加人工清理项、进度 phase=failed（spec code-fix-lane「重试仍失败则丢弃并告警」；出处 core/code_fix.py:733-763、142-213）。 | pass | 0/17 | - |
| cli-batch-worker-retry-then-success | 首次回归失败重试一次后成功：重试 run 的 prompt 注入失败用例摘要（failure_summary 非空）、二次回归 passed→合回+按 fixed 条目核销 resolved、done 按命中数累计、cleanup(success=True) 释放、链自驱动再投递遇无 open 收尾 idle（spec code-fix-lane「首次失败重试一次后成功」「回归通过则合回并核销」；出处 core/code_fix.py:713-732、804-833）。 | pass | 0/12 | - |
| cli-regression-lock-root-anchored | D10 回归锁根可锚定主树：run_regression(project_root=worktree, lock_root=主树) 执行成功（status=passed）时锁文件落在 <主树>/.fenix/full-suite.lock 且 worktree 内不另立锁、回归产物 cwd=worktree；缺省不传 lock_root 时锁回落 project_root；maintenance_runs.run_regression 门面签名含可选 project_root/lock_root（spec code-fix-lane「回归执行锁根可锚定主树」；出处 core/regression.py:533-572、710-729）。 | pass | 0/11 | - |
| cli-progress-defaults-and-roundtrip | 进度快照读写契约：文件缺失/损坏→缺省态不抛错（running=false/phase=idle/total=0/done=0 等全字段）；write_progress 合并式覆盖保留未传字段；FIX_PHASES 词表含 8 相位（spec code-fix-progress「自动修复进度结构」；出处 core/code_fix.py:44-118）。 | pass | 0/18 | - |
| cli-fixture-progress-cleanup | 夹具自愈清理：删除 seed 场景写入的 .fenix/code-review/fix-progress.json 与伪在飞 review run 三件（夹具 --reset 不覆盖 code-review/，上一轮残留会让缺省态场景跨轮 假失败——夹具供给教训）。清理后经真实读侧确认缺省态（spec code-fix-progress「无进度文件返回缺省态」；出处 bin/fixture_scheduling_showcase.py reset 范围）。 | pass | 0/5 | - |
| api-fix-progress-unknown-project-404 | GET /api/code-review/fix-progress?project=不存在项目 → 404 project not found（spec code-fix-progress「未知项目 404」；出处 core/dashboard/routes/code_review_routes.py:68-70）。 | pass | 0/2 | - |
| web-quality-tab-fix-card-layout | 设置页「质量」页签：「自动修复代码问题」卡片（开关+每批条目数输入）渲染在「周期性代码审查」开关所在卡片之后；缺省回显 enabled=false（aria-checked）、batch_size=20（spec code-fix-config「开关位于周期性代码审查下方」「设置页开关与批大小」；出处 core/dashboard/static/src/pages/settings/components/QualityPanel.tsx:384-417、settings/index.tsx:53）。 | pass | 0/8 | - |
| web-settings-agent-editors-include-code-fix | 「模型分配」面板含 Code-Fix（自动修复）角色卡（AGENT_ROLES 硬编码列表与后端同步，否则新角色在模型编辑器不可见）（spec code-fix-agent 注册点关联 D1；出处 AgentModelPanel.tsx:36-37）。注：提示词切换器下拉断言拆分至独立场景 web-settings-prompts-switcher-code-fix（web 单终态限制，下拉展开是独立页面状态）。 | pass | 0/2 | - |
| web-projects-quality-tab-default-no-card | 项目页「代码审查」页签缺省态（从未激活自动修复）：自动修复进度卡片不渲染（code-fix-progress-card 不存在），既有审查呈现（全仓库审查/当期提交审查按钮、严重度筛选）正常可用不被阻断（spec code-fix-progress「进度不影响既有审查呈现」+缺省降级；出处 CodeFixProgressCard.tsx:124-132、QualityTab.tsx:594-660）。 | pass | 0/4 | - |
| api-fix-progress-default-state | GET /api/code-review/fix-progress?project=scheduling-showcase 缺省态：200 + {running:false,phase:idle,total:0,done:0}（夹具每轮 reset 无进度文件，读侧 MUST NOT 500）（spec code-fix-progress「无进度文件返回缺省态」「进度只读 API」；出处 core/dashboard/routes/code_review_routes.py:58-71、core/dashboard/routes/base.py:328）。 | pass | 0/6 | - |
| web-quality-tab-fix-batch-empty-rejected | 设置页批大小清空后保存：表单校验拒绝并显示「须为 1–1000 的整数」，配置不落盘（前端 validator 与后端同口径）（spec code-fix-config「非法值拒绝落盘」UI 半边；出处 QualityPanel.tsx:402-412）。 | pass | 0/2 | - |
| web-settings-prompts-switcher-code-fix | 设置页「提示词」Agent 切换器下拉含 Code-Fix（自动修复）选项（AGENT_LABELS 硬编码列表与后端注册点同步，否则新角色提示词不可编辑）（spec code-fix-agent 注册点关联 D1；出处 PromptsPanel.tsx:28-30、144-145）。交互注记：下拉 12 项超过 listHeight 256px，antd rc-virtual-list 虚拟滚动使末两项不进 DOM，需键盘 ArrowDown 驱动高亮滚动后再断言（type+window+按键名=引擎键盘按键通路）。 | pass | 0/1 | - |
| cli-seed-fixture-progress-running | 给夹具项目 scheduling-showcase 写自动修复运行中进度（running/fixing/total 60/done 20/第 2 批）并在飞审查 run（manifest+out+runs 事件行），供 api/web 场景在真实实例上读取渲染；写后回读校验（依赖：夹具由 verify.yaml prepare 幂等供给，出处 .fenix/verify.yaml:59-63、core/code_fix.py:103、core/code_review.py:46-53）。 | pass | 0/9 | - |
| web-quality-tab-fix-switch-save-persist | 项目级作用域打开「自动修复代码问题」并把批大小 20→50 保存：重进设置页回显开关 aria-checked=true、批大小 50；随后复原关闭并保存（避免残留状态）（spec code-fix-config「开关可开启并持久化」「批大小可改」；出处 QualityPanel.tsx:53-56、181-184）。 | failed（已修正） | 2/2 | test-defect |
| api-fix-progress-seeded-running | GET /api/code-review/fix-progress?project=scheduling-showcase 运行态：200 + running:true、phase:fixing、total:60、done:20、batch_no:2、current 含「第 2 批」（端点读真实落盘进度，非 mock）（spec code-fix-progress「修复中可查真实进度」「读取进度」；出处 core/dashboard/routes/code_review_routes.py:58-71）。 | pass | 0/8 | - |
| api-config-crf-invalid-rejected | POST /api/config?project=scheduling-showcase 提交 code_review_fix.batch_size=0 → 400 且文案含 must be a positive integer，配置保持原值不半写（spec code-fix-config「非法值拒绝落盘」；出处 core/dashboard/routes/settings_routes.py:49-56、core/dashboard/data/config_admin.py:1229-1240）。 | failed（已修正） | 2/3 | test-defect |
| web-projects-quality-tab-running-progress | 自动修复运行中：项目页「代码审查」页签渲染进度卡片——「已处理 20/60 条」「第 2 批 · 修复中」与约 33% 进度条（total=60 done=20）（spec code-fix-progress「显示已处理/总数与进度条」；出处 CodeFixProgressCard.tsx:140-159）。 | pass | 0/4 | - |
| api-config-crf-save-echo-restore | POST /api/config?project=scheduling-showcase 写 {enabled:true,batch_size:30} → 200 saved=true；GET /api/config?project= 回显 enabled=true/batch_size=30 且 sources.admin.code_review_fix=project；再 POST 恢复缺省 {false,20}（spec code-fix-config「保存后回显」；出处 core/dashboard/routes/settings_routes.py:40-67、core/dashboard/data/config_admin.py:257-259）。 | failed（已修正） | 3/6 | test-defect |
| web-projects-quality-tab-two-progress-coexist | 两条进度并存：审查进行中卡片（审查进行中（periodic）·1/2 文件，来自 seed 伪在飞 review run）与自动修复进度卡片同屏同时渲染，互不覆盖（spec code-fix-progress「两条进度并存」；出处 QualityTab.tsx:675-703）。 | pass | 0/5 | - |
| cli-seed-fixture-progress-blocked | 把夹具进度改写为 blocked 终态（reason=regression_contract_missing）并清理在飞审查 run 假件，供 web blocked 态场景断言（依赖前序运行态场景已消费 running 态；出处 core/code_fix.py:103-118）。 | pass | 0/7 | - |
| web-projects-quality-tab-blocked-reason | 阻塞态可见原因：进度 blocked 时页签展示「已阻塞」与「原因：regression_contract_missing」，不以运行中形态无限轮询（spec code-fix-progress「阻塞态可见原因」；出处 CodeFixProgressCard.tsx:31-45、148-158）。 | pass | 0/4 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| cli-run-id-prefix-attribution | json_output path=unknown expected [agent, planner-plan-42]（未知前缀回退泛型） | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景把已注册前缀当未知示例：run_files.py RUN_ID_AGENT_PREFIXES 含 ("planner-plan-","planner-plan")，返回 (planner-plan,42) 系产品正确归属（docstring：未识别前缀才回退 agent）；修复=改用真未知前缀 custom-... |
| web-quality-tab-fix-switch-save-persist | attribute_match aria-checked expected true actual false（code-review-fix-enabled-switch） | test-defect | 测试用例自身缺陷（非产品缺陷） | 复原步骤（14-17：点开关+type 20+save）先于断言执行；终态 false 恰为复原目标态——若 phase-1 保存未持久化，重导航后点击会把开关翻成 true，终态应为 true，实际 false 反证持久化生效 |
| web-quality-tab-fix-switch-save-persist | text_match batch-size expected 50 actual 20 | test-defect | 测试用例自身缺陷（非产品缺陷） | 同上绑定终态：复原步骤已把输入改回 20 并保存，断言检的是复原后终态而非持久化终态；web 场景单终态限制（引擎在全部步骤后统一断言） |
| api-config-crf-invalid-rejected | status_code expected 400 actual 200（非法值 400 拒绝） | test-defect | 测试用例自身缺陷（非产品缺陷） | 断言未设 response 绑定，缺省=最近一次响应（步骤2 GET 200 配置回显）而非步骤1 POST；POST 3ms 延迟符合校验快速失败；同实例复现三次均 HTTP 400 + "admin.code_review_fix.batch_size must be a positive integer: 0" |
| api-config-crf-invalid-rejected | body_contains expected 'must be a positive integer' | test-defect | 测试用例自身缺陷（非产品缺陷） | 同一绑定缺陷：错误文案在 POST 400 响应体，断言却在 GET 配置回显体中检索（actual_snippet=llm 配置串）必然失配 |
| api-config-crf-save-echo-restore | json_path code_review_fix.enabled expected true actual false（回显 enabled=true） | test-defect | 测试用例自身缺陷（非产品缺陷） | 断言缺省绑定步骤3 restore 响应（其设计值即 false），未绑步骤2 GET 回显捕获；复现三连 save/echo 全部正确 |
| api-config-crf-save-echo-restore | json_path code_review_fix.batch_size expected 30 actual 20（回显 batch_size=30） | test-defect | 测试用例自身缺陷（非产品缺陷） | 同上：restore 响应设计值即 20；GET 回显实测 {'enabled': True, 'batch_size': 30} |
| api-config-crf-save-echo-restore | json_path sources.admin.code_review_fix expected 'project' actual None | test-defect | 测试用例自身缺陷（非产品缺陷） | 同上绑定错位；同实例三次复现（含运行前无段状态+keep-alive 快时序）save/GET/restore 响应 sources 均=project |

## 本轮场景集变更

当前稳定场景集共 31 个（第 1 轮）。

- 首轮写入 31 个场景

