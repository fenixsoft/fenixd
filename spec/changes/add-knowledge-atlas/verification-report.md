# 验证报告：add-knowledge-atlas

> ⚠️ 本报告由框架于 2026-09-27T05:49:51Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-27T05:40:00.832031+00:00

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 17/21 场景通过，4 失败，0 错误（2 个真实产品 Bug）**

21 场景：17 PASS，4 FAIL（2 product-bug + 2 test-defect）。product-bug：①ADR 索引视图缺标题字段（major，数据链路缺口，影响 web-knowledge-adr-view）；②禁用占位文案漂移（minor，SPEC「已禁用」vs 实现「未启用」，影响 web-knowledge-disabled-placeholder）。test-defect：两场景断言在点击/导航后评估结构性必败，已原地修复拆分（repaired 2 + added 2，无移除），分类均 test-defect 映射 failed。静态情报 web-settings-knowledge-control「归档」二字文本选择器判误报：本轮实测该选择器 click 与 no_click_interception 均通过（antd Menu 项不触发 autoInsertSpace，仅 Button 触发），无需修复。

| 指标 | 数量 |
| --- | --- |
| 通过 | 17 |
| 失败 | 4 |
| 错误 | 0 |
| 产品 Bug | 2 |
| 本链增量 Token（输入） | 9.09M |
| 本链增量 Token（输出） | 0.14M |


## 真实产品 Bug

### BUG-01（severity=major）· text_contains

- 关联场景：web-knowledge-adr-view
- 描述：ADR 索引视图缺「标题」列：SPEC knowledge-dashboard-tab spec.md:14 要求列表渲染「编号、标题、状态标签」，实测 adr/index.md 表格标题（zn-adr-one-title / zn-adr-two-title）均不在页面文本，列表项以文件名派生名（ADR-001-zn-one）替代标题
- 根因：ADR 列表数据链路无标题字段：后端 GET /api/knowledge/index 的 adrs 仅含 {file,status,superseded_by}（core/dashboard/routes/knowledge_routes.py:80、128-131，_parse_adr_head 只解析 status/superseded_by），前端列表标题用 adrDisplayName(file) 文件名派生（core/dashboard/static/src/pages/projects/components/KnowledgeTab.tsx:288），adr/index.md 表格中的标题从未进入渲染数据
- 证据（场景 web-knowledge-adr-view 结构化证据，引用）：
  - failed_assertions: [{"type": "text_contains", "text": "zn-adr-one-title", "expected": "ADR-001 标题在 ADR 视图中", "actual": "页面文本无该标题（列表项标题为文件名派生）"}, {"type": "text_contains", "text": "zn-adr-two-title", "expected": "ADR-002 标题在 ADR 视图中", "actual": "页面文本无该标题"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/add-knowledge-atlas/screenshots/web-knowledge-adr-view_assert_fail.png"]
  - first_failed_step: 步骤5 wait [data-testid=knowledge-adr-list] 成功、状态字面 superseded 在场，但 adr/index.md 表格中的两条标题（zn-adr-one-title/zn-adr-two-title）均不在页面文本：后端 /api/knowledge/index 的 adrs 仅含 {file,status,superseded_by}（knowledge_routes.py:80），前端列表标题用 adrDisplayName(a.file) 文件名派生（KnowledgeTab.tsx:288），index.md 标题从未进入渲染数据链路

### BUG-02（severity=minor）· element_visible

- 关联场景：web-knowledge-disabled-placeholder
- 描述：禁用态占位文案漂移：SPEC knowledge-config spec.md:5 钉死占位文案「知识真相源已禁用」，实现渲染「知识真相源未启用」（占位卡片、页签保留等功能行为均正常）
- 根因：实现文案未对齐 SPEC 契约字面：core/dashboard/static/src/pages/projects/components/KnowledgeTab.tsx:157 为「知识真相源未启用」，应改为「知识真相源已禁用」（或经 SPEC 变更流程确认新文案）
- 证据（场景 web-knowledge-disabled-placeholder 结构化证据，引用）：
  - failed_assertions: [{"type": "element_visible", "selector": "[data-testid=\"knowledge-disabled-card\"]:has-text(\"知识真相源已禁用\")", "expected": "禁用占位含 SPEC 契约文案「知识真相源已禁用」", "actual": "Locator.wait_for Timeout——卡片在场（步骤5 wait testid 成功）但文案为「知识真相源未启用」"}, {"type": "text_contains", "text": "知识真相源已禁用", "expected": "页面文本含「知识真相源已禁用」", "actual": "全文无该字面，实现渲染「知识真相源未启用」"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/add-knowledge-atlas/screenshots/web-knowledge-disabled-placeholder_assert_fail.png"]
  - first_failed_step: 禁用占位文案漂移：SPEC knowledge-config spec.md:5 钉死「知识真相源已禁用」，实现 KnowledgeTab.tsx:157 渲染「知识真相源未启用」，占位功能在场（testid 卡片 wait 成功）仅契约文案不匹配


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-knowledge-skeleton-tracked | 真相源目录骨架存在且入库（knowledge-atlas-directory「首次初始化后目录骨架存在且入库」）：spec/knowledge/README.md 在场且说明目录契约（域/能力/ADR 布局、marker 格式、150 行硬顶、溯源行格式，tasks 1.3），且该目录已被 git 跟踪（首跑前允许只含 README 骨架）。出处：spec/changes/add-knowledge-atlas/tasks.md:34、specs/knowledge-atlas-directory/spec.md。 | pass | 0/6 | - |
| cli-config-knowledge-registered | knowledge 配置段登记与缺省值（knowledge-config「知识真相源配置项」）：core/config.py 含 knowledge 段解析（enabled bool 缺省 true，tasks 1.1），config.template.yaml 登记模板行且 enabled 缺省 true（经 YAML 解析实测模板行真值，非仅 grep 字面）。出处：spec/changes/add-knowledge-atlas/tasks.md:32、specs/knowledge-config/spec.md、design.md:59-61（D6）。 | pass | 0/4 | - |
| cli-distill-mount-contract | 蒸馏管线单点挂载与核心函数（knowledge-distill-pipeline「归档触发蒸馏」、design D3）：core/archive_commit.py 在双归档路径共同漏斗 commit_archive_move 上挂 dispatch_distill，core/knowledge.py 提供 validate_knowledge 与 dispatch_distill，蒸馏提示词 core/knowledge_prompts/distill.md 在场且含 ADDED/MODIFIED/REMOVED 合并语义与 150 行硬顶契约。出处：spec/changes/add-knowledge-atlas/design.md:42-44、tasks.md:38-41。 | pass | 0/7 | - |
| cli-knowledge-unit-tests | 知识机制单测全量通过：pytest -k "knowledge or distill" 运行本 SPEC 新增单测（tasks 1.1 配置解析回读、2.3 双路径挂载、2.4 fake spawn 三支路、3.2 路由冒烟含路径穿越 400、4.1/4.2 前端渲染）。真实蒸馏 LLM run 与归档事件流不可在验证窗口确定性驱动，knowledge.enabled=false 归档静默跳过派发（knowledge-config「禁用后全链静默」派发半边）等治理 MUST 路径以单测为权威载体（对齐 add-project-architecture-tab cli-arch-unit-tests 先例）。出处：spec/changes/add-knowledge-atlas/tasks.md:32/40/41/46/51-52。 | pass | 0/2 | - |
| cli-validate-clean-tree | validate_knowledge 对合法真相源树零崩溃放行（蒸馏收尾确定性校验正向半边）：在 /tmp 合成最小合法树（marker 可解析、sources 指向真实存在的 spec/archive/ 子目录、单页远小于 150 行、index/_domain 链接可解析）后调用 core/knowledge.py::validate_knowledge(project_root)。校验器报告形态（返回值结构/是否抛异常）不由 SPEC 钉死，本场景只断言「合法树不抛异常、退出码 0」，并回显原始返回供 judge 审计；违规拦截语义由三个违规场景承载。出处：spec/changes/add-knowledge-atlas/tasks.md:38、design.md:37（D2）。 | pass | 0/2 | - |
| api-knowledge-index-alive | 知识总目录端点存活（knowledge-dashboard-tab 后端契约、design D5）：GET /api/knowledge/index?project=fenixd 返回 200——未初始化（index.md 尚未由蒸馏产出）时返回占位结构亦为 200（存在性探测语义非报错），故本断言对初始化前后两态均成立、与夹具注入时序无关。端点出处：spec/changes/add-knowledge-atlas/design.md:55、tasks.md:45（实现前规划，契约由 SPEC 钉死）。 | pass | 0/1 | - |
| api-knowledge-file-path-guard | 知识文件端点路径穿越与前缀白名单拒绝（knowledge-dashboard-tab「路径穿越被拒绝」、design D5「白名单前缀（domains/、adr/）外的路径与 .. 一律 400」）：①path=../../.fenix/STATE.md（穿越敏感文件）②path=README.md（白名单前缀外）③path=domains/../zn-secret.md（前缀内夹 ..）——三者恒 400，不泄露任何文件内容。端点出处：spec/changes/add-knowledge-atlas/design.md:56、tasks.md:45。 | pass | 0/3 | - |
| api-knowledge-graph-missing-404 | 关系图端点在位可取（knowledge-dashboard-tab graph 契约，前提更新）：spec/knowledge/graph/ 已由后续 SPEC add-knowledge-atlas-maintenance 交付（2026-09-27 judge 实测在场），GET /api/knowledge/graph 返回 200 且响应体为 graph 页内容（探针串 graph-probe-fixture）。原「缺位恒 404」断言前提失效，按交付后契约改为 200 + 内容断言（强化：404→200+body）。出处：spec/changes/add-knowledge-atlas/design.md:57、tasks.md:45。 | pass | 0/2 | - |
| web-knowledge-tab-position | 「项目知识」页签插入位置（knowledge-dashboard-tab「项目知识页签」）：项目页 Tabs 共 6 个（既有 5 个不动 + 新增 1 个），「项目知识」位于「项目架构」之后、「会话接入」之前（SPEC 钉死插入点）。顺序断言用 antd Tabs 真实渲染结构的 ~ 兄弟组合器（先例 add-project-architecture-tab web-arch-tab-order-gating 实测同款）。出处：SPA 路由 /projects/:name（core/dashboard/static/config/routes.ts:27-28），hash 路由（core/dashboard/static/config/config.ts:15），页签数组 core/dashboard/static/src/pages/projects/list.tsx:1317-1477（architecture=1451、session=1460 之间为 SPEC 钉死插入点）。 | pass | 0/5 | - |
| web-knowledge-tab-lazy-graph-placeholder | 页签按需加载与 graph 占位（knowledge-dashboard-tab「页签位置与按需加载」+「graph 缺位时占位」）：默认「功能开发」分面下知识面板内容不在 DOM（antd Tabs 惰性挂载，「未选中零请求」的可观察代理，同 ArchitectureTab 门控先例口径）；点选「项目知识」后知识面板惰性挂载、graph 区渲染（graph/ 已由 maintenance SPEC 交付，实测渲染 iframe，原占位断言前提失效）。2026-09-27 judge 修复：antd ^6.6.0 面板 class 为 .ant-tabs-content-active（v5 .ant-tabs-tabpane 已不存在），选择器对齐实测渲染形态；graph 断言改为 iframe 在场。出处：SPA 路由 /projects/:name（core/dashboard/static/config/routes.ts:27-28），hash 路由（core/dashboard/static/config/config.ts:15）。 | failed（已修正） | 1/5 | test-defect |
| web-settings-knowledge-control | 设置页 knowledge.enabled 控件在场（knowledge-config「设置页可见可改」）：开关位于设置页「归档」页签 MiscSettingsPanel 的 knowledge-settings-card（无独立「知识」菜单项——原场景臆测失配，judge 实测 PAGE_LABELS 全表无 knowledge 项；antd Switch 渲染 button[role=switch]，data-testid=knowledge-enabled-switch，MiscSettingsPanel.tsx:178）。不做保存点击避免污染用户级配置（持久化半边由 api-config-knowledge-disable/restore 承载）。2026-09-27 judge 修复：导航改为「归档」菜单项，断言对齐实际渲染 testid（键名不以 label-note 字面呈现，说明文案由 knowledge-enabled-desc 承载），断言强度不变。出处：core/dashboard/static/src/pages/settings/components/MiscSettingsPanel.tsx、导航 http://127.0.0.1:32985/#/settings（core/dashboard/static/config/routes.ts:37-39）。 | pass | 0/6 | - |
| cli-validate-marker-violation | 校验器拦截 marker 违规页（knowledge-atlas-directory「marker 机器可解析」反向）：合成缺失 capability 键的 marker 能力页（capability 名 znq-broken-marker-cap 同时内嵌于页名），validate_knowledge 须报告违规且报告可定位（SPEC 设计：违规反馈给蒸馏 run 修正，报告必含违规方标识——页路径或 capability 名其一即可命中公共 token znq-broken-marker）。出处：specs/knowledge-atlas-directory/spec.md marker 契约段、design.md:37。 | pass | 0/2 | - |
| cli-validate-dangling-source | 校验器拦截悬空溯源链接（knowledge-distill-pipeline「溯源链接悬空被拦截」）：合成 sources 指向不存在归档目录 spec/archive/zn-dangling-archive-missing 的能力页（页名 zn-dangling-src-cap.md 与悬空目录名共享公共 token zn-dangling，报告引页路径或引悬空目录均命中）。出处：specs/knowledge-distill-pipeline/spec.md「溯源链接悬空被拦截」场景、tasks.md:38。 | pass | 0/2 | - |
| cli-validate-overlimit | 校验器拦截超顶页（knowledge-atlas-directory「蒸馏产出超顶页被拦截」）：合成 170 行（>150 硬顶）且 marker/sources 均合法的能力页 zn-overlimit-cap.md，validate_knowledge 须报告行数违规且报告含该页标识（蒸馏 run 须拆页或精简后重写，最终落盘版本不超 150 行——拦截动作由本断言的「报告可定位」承载）。出处：specs/knowledge-atlas-directory/spec.md「单页行数硬顶」、tasks.md:38。 | pass | 0/2 | - |
| cli-seed-knowledge-fixtures | 注入真相源夹具（供内容渲染类场景确定性驱动）：向验证树 spec/knowledge/ 写入合法 index.md、域清单 _domain.md、能力页（marker sources 运行时动态取 spec/archive/ 首个真实归档目录，溯源链接不悬空）、adr/index.md 与两条 ADR（ADR-001 superseded / ADR-002 accepted 构成取代链）。种子的是夹具内容而非被测端点——/api/knowledge/* 三端点全部打真实实例（被测端点禁 mock 铁律）。夹具 token：znidx-atlas-index-title / zn-demo-capability / zn-cap-rule-marker / zn-adr-*-title。出处：specs/knowledge-atlas-directory/spec.md 目录结构与能力页契约、specs/knowledge-adr-index/spec.md supersede 链。 | pass | 0/4 | - |
| api-knowledge-file-content-whitelist | 知识文件端点白名单内真读真回（knowledge-dashboard-tab「后端返回该能力页文件内容」）：夹具注入后，domains/ 前缀能力页、adr/index.md 与 _domain.md 均返回 200 且响应体含夹具特征串（zn-cap-rule-marker / zn-adr-two-title）——后端真实读取 spec/knowledge/ 下文件，不 mock 被测端点（禁 mock 铁律）。端点出处：spec/changes/add-knowledge-atlas/design.md:56、tasks.md:45。 | pass | 0/5 | - |
| web-knowledge-index-render-and-nav | 总目录渲染与能力页导航（knowledge-dashboard-tab「浏览总目录并进入能力页」）：选中页签后 index.md 以 Markdown 渲染（夹具标题 znidx-atlas-index-title 可见），点击 index 中的能力链接（夹具 href=API path 参数形态 domains/<域>/<能力>.md，链接文本 zn-demo-capability）进入能力页渲染——规则散文（zn-cap-rule-marker）与溯源段在场。夹具由 cli-seed-knowledge-fixtures 注入验证树、状态经被测应用传递（depends_on 串接）。出处：SPA 路由 /projects/:name（core/dashboard/static/config/routes.ts:27-28），hash 路由（core/dashboard/static/config/config.ts:15），页签数组 core/dashboard/static/src/pages/projects/list.tsx:1317-1477（architecture=1451、session=1460 之间为 SPEC 钉死插入点）。 2026-09-27 judge 修复：antd ^6.6.0 下面板 class 变更，等待/断言选择器对齐产品实际渲染 testid（knowledge-index-view/knowledge-page-view），断言强度不变。 | failed（已修正） | 2/6 | test-defect |
| web-knowledge-adr-view | ADR 索引视图（knowledge-dashboard-tab ADR 视图）：页签提供 ADR 索引视图，accepted 与 superseded 条目（编号/标题/状态）可见、superseded 条目保留在列供溯源。夹具经 adr/index.md 提供两条 ADR（ADR-001 zn-adr-one-title superseded / ADR-002 zn-adr-two-title accepted，构成取代链）；视图若为结构化渲染，状态标签自 status 派生；若直渲染 index.md 原文，状态字面同样在场——两种实现形态断言等价。出处：SPA 路由 /projects/:name（core/dashboard/static/config/routes.ts:27-28），hash 路由（core/dashboard/static/config/config.ts:15），页签数组 core/dashboard/static/src/pages/projects/list.tsx:1317-1477（architecture=1451、session=1460 之间为 SPEC 钉死插入点）。 2026-09-27 judge 修复：antd ^6.6.0 面板 class 变更，等待/断言选择器对齐 knowledge-adr-list testid，断言强度不变。 | failed（已修正） | 2/5 | product-bug |
| api-config-knowledge-disable | 禁用 knowledge.enabled 并读回确认（knowledge-config「禁用后全链静默」前置 + 「设置页可见可改」持久化半边）：经既有配置 POST 链路（设置页保存同款后端、用户级作用域）写 knowledge.enabled=false，响应读回与 GET /api/config 复读均须为 false——热更新生效、无需重启 daemon。禁用态供 web 禁用占位场景消费，恢复由 api-config-knowledge-restore 承载（本场景排在全部 enabled 态场景之后，depends_on 钉死时序）。端点出处：core/dashboard/routes/settings_routes.py:92（_api_config_post，既有链路）、spec/changes/add-knowledge-atlas/tasks.md:33、specs/knowledge-config/spec.md。 | pass | 0/5 | - |
| web-knowledge-disabled-placeholder | 禁用态页签占位（knowledge-config「禁用后全链静默」前端半边）：knowledge.enabled=false 时项目知识页签显示「知识真相源已禁用」占位而非报错（SPEC 钉死文案），页签本身仍在（proposal：禁用后页签显禁用占位）。前置 api-config-knowledge-disable 已置 false；wait 31s 兜底后端配置 30s mtime 热更新窗口（前端 GET /api/config 每次直读文件，此等待仅对「页签禁用态取自服务端缓存」的实现形态生效，对直读形态无害）。出处：SPA 路由 /projects/:name（core/dashboard/static/config/routes.ts:27-28），hash 路由（core/dashboard/static/config/config.ts:15），页签数组 core/dashboard/static/src/pages/projects/list.tsx:1317-1477（architecture=1451、session=1460 之间为 SPEC 钉死插入点）。 2026-09-27 judge 修复：antd ^6.6.0 面板 class 变更，等待/断言选择器对齐 knowledge-disabled-card testid；SPEC 钉死文案断言「知识真相源已禁用」原样保留不弱化（实现 KnowledgeTab.tsx:157 为「知识真相源未启用」，重执行预期暴露该产品文案漂移）。 | failed（已修正） | 2/4 | product-bug |
| api-config-knowledge-restore | 恢复 knowledge.enabled=true（删除/撤销类回归点：状态操作后与操作前对比，验证实例配置复位避免跨场景污染）：同款 POST 链路写回 true，写入响应与 GET 复读均须为 true。端点出处：core/dashboard/routes/settings_routes.py:92（既有链路）、specs/knowledge-config/spec.md。 | pass | 0/4 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| web-knowledge-tab-lazy-graph-placeholder | element_not_exist [data-testid="knowledge-index-view"] 默认分面下知识面板不在 DOM | test-defect | 测试用例自身缺陷（非产品缺陷） | 断言次序与引擎「步骤先行、断言后置」模型冲突：步骤4 click「项目知识」页签成功后面板已挂载，element_not_exist 后置执行结构性必败；「未选中不在 DOM」语义在该引擎下不可表达，属场景设计缺陷。页签/面板渲染正常由同轮 web-knowledge-tab-position（6 页签、位置断言... |
| web-knowledge-index-render-and-nav | text_contains "znidx-atlas-index-title" 总目录标题在页面文本中 | test-defect | 测试用例自身缺陷（非产品缺陷） | 断言时序错置：引擎断言后置执行，步骤6已点击能力链接、页面已切至能力页视图，index 标题自然不在当前文本。标题渲染已在步骤5 wait [data-testid=knowledge-index-view]:has-text(znidx-atlas-index-title) 成功验证，产品无缺陷 |
| web-knowledge-index-render-and-nav | no_click_interception a:has-text("zn-demo-capability") 能力链接不被遮挡 | test-defect | 测试用例自身缺陷（非产品缺陷） | 断言自带重点击（error=Locator.click Timeout waiting for locator），此时链接已因步骤6成功点击随 SPA 导航从 DOM 移除，非遮挡所致；步骤6 click 成功即证明点击未被遮挡。导航型链接不适配该断言的目标存活前提，属场景设计缺陷 |

## 本轮场景集变更

当前稳定场景集共 21 个（第 1 轮）。

- 首轮写入 21 个场景

