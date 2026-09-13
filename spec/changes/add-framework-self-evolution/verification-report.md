# 验证报告：add-framework-self-evolution

> ⚠️ 本报告由框架于 2026-09-13T10:53:07Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-12T23:25:33.520781+00:00

## 结论：✅ 通过（verified）

**状态：verified — 42/42 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 42/42 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 42 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 32.33M |
| 本链增量 Token（输出） | 0.32M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-seed-evolution-fixtures | 种子场景：向验证实例框架根 .fenix/evolution/ 写入建议改进项夹具——items.jsonl 10 条覆盖全部 7 种状态（pending×4/analyzed/draft_failed/accepted/auto_accepted/rejected/accept_failed）+ 4 个 pending 条目的草稿目录（proposal.md/design.md/tasks.md/specs/<cap>//spec.md/.spec.yaml），供 API/web 场景经 depends_on 串接消费（add-verify-multi-kind-runner 同款 seed 边界：CLI 缺省 cwd=验证树根，与 dashboard 读侧 FRAMEWORK_ROOT 同源，写入即被 /api/evolution/items 读到）。出处：core/evolution.py:128-215（items.jsonl 存储/原子写）、:565-617（draft 目录五件套）；dashboard 读侧 core/dashboard/data.py:5056-5089 read_evolution_items。 | pass | 0/6 | - |
| cli-evolution-item-id-stability | 条目身份键跨环境稳定（self-evolution spec「身份键跨环境稳定」）：同一（项目/日期节/小节/标题）四元组两次计算 id 一致且为 12 位，标题变化后 id 变化，与渲染顺序/行号无关。出处：core/evolution.py:70-80 item_id（sha1 前 12 位）。 | pass | 0/5 | - |
| cli-evolution-todo-parse | todo.md 条目解析（self-evolution spec「增量水位与条目幂等」上游 2.5）：三小节 + 四字段解析完整；「（当日无）」占位与未知小节条目被跳过且不使解析失败。出处：core/evolution.py:427-531 parse_todo_entries。 | pass | 0/7 | - |
| cli-evolution-ready-scan | 就绪扫描五分支（self-evolution spec「自进化触发与就绪扫描」）：self_review_state.json 缺失（p2）/todo.md 空（p3）/last_run_at 不晚于水位（p4）均不就绪且不告警，仅 p1 就绪；无水位记录时 last_run_at 存在即就绪。出处：core/evolution.py:354-426 scan_ready_projects。 | pass | 0/5 | - |
| cli-evolution-ingest-lint-gate | 草稿生成与同源 lint 硬门（self-evolution spec「草稿生成与同源 lint 校验」3.3）：worth_spec=true 且 spec 齐全、tasks.md 无声明段 → lint 通过 → 置 pending 且草稿五件套落盘；worth_spec=false → 置 analyzed 且不建草稿；tasks.md 声明 modify 但目标文件不存在 → lint violation → 置 draft_failed 且草稿目录被删除（不留半成品）。出处：core/evolution.py:570-658（materialize_draft/lint_draft）、:660-730（ingest_item）。 | pass | 0/8 | - |
| api-evolution-items-list | 建议改进项列表端点（self-evolution spec「自进化 API 契约」列表语义）：GET /api/evolution/items 返回 200，每条含 id/project/date_section/section/title/verdict/status/has_draft/spec_name/created_at/decided_at，按入库时间（created_at）倒序——夹具最新条目 A（created 08:00）居首、最旧 J（07:51）居末。出处：core/dashboard/server.py:411,1806-1812；core/dashboard/data.py:5056-5089 read_evolution_items。 | pass | 0/8 | - |
| api-evolution-items-project-filter | 列表 project 过滤（自进化 API 契约「可选 project」）：?project=fenixd 仅返回 fenixd 项目 3 条（D/H/J），仍按入库时间倒序，且 summary 字段齐全（含 spec_name/decided_at）。出处：core/dashboard/server.py:1806-1812；data.py:5056-5089。 | pass | 0/7 | - |
| api-evolution-analysis-ok | 分析结论端点（自进化 API 契约「返回 analysis_md 原文」）：GET /api/evolution/analysis?item_id=13c45087fe8d → 200 + {found:true, content}，content 含三项判定与证据标记。出处：core/dashboard/server.py:413,1814-1827；data.py:5091-5104 read_evolution_analysis。 | pass | 0/4 | - |
| api-evolution-analysis-400 | 分析结论端点缺参（自进化 API 契约「参数缺失/非法 MUST 返回 400 且不触碰任何文件」）：GET /api/evolution/analysis 无 item_id → 400 与可读错误。出处：core/dashboard/server.py:1815-1820。 | pass | 0/2 | - |
| api-evolution-analysis-404 | 分析结论端点未知条目（自进化 API 契约「item_id 未知 MUST 返回 404」）：item_id=does-not-exist-xyz → 404 且不读取任何文件。出处：core/dashboard/server.py:1822-1826。 | pass | 0/2 | - |
| api-evolution-draft-four-docs | 草稿文档端点四类 doc（自进化 API 契约「doc 白名单 proposal\|design\|tasks\|spec」）：对条目 A 分别请求四种 doc，均 200 + found:true 且内容含各自标记。出处：core/dashboard/server.py:415,1829-1851；data.py:5106+ read_evolution_draft。 | pass | 0/9 | - |
| api-evolution-draft-invalid-doc-400 | 草稿端点非法 doc（自进化 API 契约「doc 超出白名单 MUST 返回 400」）：doc=readme → 400 且 MUST NOT 读取草稿目录之外的任何文件。出处：core/dashboard/server.py:1837-1842；data.py:5106+。 | pass | 0/2 | - |
| api-evolution-draft-unknown-404 | 草稿端点未知条目（自进化 API 契约「item_id 未知 MUST 返回 404」）：→ 404 且不读取任何文件。出处：core/dashboard/server.py:1844-1848。 | pass | 0/2 | - |
| api-evolution-draft-found-false | 草稿已删除空态（自进化 API 契约「条目存在但草稿不存在返回 found:false」）：对已 accepted 的条目 G（60541ecd74bf，草稿随接受流程删除）请求草稿 → 200 + found:false。出处：core/dashboard/server.py:1829-1851；data.py:5106+。 | pass | 0/2 | - |
| api-evolution-accept-pending | 接受路径全链（self-evolution spec「人工同意完成立项全链」）：POST /api/evolution/accept {item_id:13c45087fe8d}（pending）→ 200 + {ok:true, status:accepted, spec_name:evo-fixture-overview-latency}；读侧复查 /api/evolution/items 首位 A 状态变 accepted。接受会复制草稿到 spec/changes/evo-fixture-overview-latency/、仅 add 该目录提交、StateMachine.add_spec(drafted, priority=5)。出处：core/dashboard/server.py:1950,1853-1882；core/evolution.py:821-940 accept_item。 | pass | 0/6 | - |
| api-evolution-accept-idempotent | 重复同意幂等（self-evolution spec「重复同意幂等」）：对已 accepted 的 A 再次 POST accept → 200 + 返回当前状态，不产生第二次提交/注册。出处：core/evolution.py:828-833（非 pending/accept_failed 幂等返回现状）。 | pass | 0/4 | - |
| api-evolution-accept-name-suffix | 重名自动加后缀（self-evolution spec「重名自动加后缀」）：条目 K（spec.name=fixture-conflict，spec/changes/evo-fixture-conflict 与 STATE.md 均已由种子预置）POST accept → 名称消解为 evo-fixture-conflict-9dd6df（追加 id 前 6 位）且注册前再次确认唯一 → 200 + spec_name 带后缀。出处：core/evolution.py:732-775 resolve_spec_name；core/dashboard/server.py:1853-1882。 | pass | 0/6 | - |
| api-evolution-accept-unknown-404 | 接受端点未知条目（自进化 API 契约「item_id 未知 MUST 返回 404」）：→ 404。出处：core/dashboard/server.py:1871-1873。 | pass | 0/2 | - |
| api-evolution-accept-missing-param-400 | 接受端点缺参（自进化 API 契约「参数缺失 MUST 返回 400」）：空 body → 400。出处：core/dashboard/server.py:1858-1863。 | pass | 0/2 | - |
| api-evolution-reject-pending | 拒绝路径（self-evolution spec「拒绝删除草稿并落状态」）：POST /api/evolution/reject {item_id:e62c6a533dd4}（pending）→ 200 + {ok:true, status:rejected}，草稿目录被删除；读侧复查 ?project=fenixd 首位 D has_draft=false 且状态 rejected。出处：core/dashboard/server.py:1952,1884-1899；core/evolution.py:958-999 reject_item。 | pass | 0/6 | - |
| api-evolution-reject-accepted-error | 已接受条目不可拒绝（self-evolution spec「已接受条目不可拒绝」）：对已 accepted 的 A POST reject → 200 + ok:false + 状态 accepted 且错误文案，草稿/STATE 均不变。出处：core/evolution.py:971-975（状态不在可拒绝集合返回错误且不改动任何文件）。 | pass | 0/4 | - |
| api-evolution-reject-unknown-404 | 拒绝端点未知条目（自进化 API 契约「item_id 未知 MUST 返回 404」）：→ 404。出处：core/dashboard/server.py:1892-1894。 | pass | 0/2 | - |
| api-config-user-scope-roundtrip | 用户级配置读写往返（self-evolution spec「用户级作用域读写往返」/配置节）：GET /api/config（用户级）self_evolution 缺省 auto_accept=false、max_items_per_run=20；POST 写入 {auto_accept:true, max_items_per_run:25} → 200 回显新值；随后写回缺省 {false,20} 还原（恢复机器配置，避免污染运行时）。出处：core/dashboard/data.py:4204-4207（读侧注入缺省）、:4695-4720（写侧校验）；core/config.py:989-1017 get_self_evolution_config。 | pass | 0/8 | - |
| api-config-invalid-value-400 | 非法配置值 400 不写盘（self-evolution spec「非法值被拒绝」/配置节）：max_items_per_run=0 → 400 且错误文案含 must be an integer in；auto_accept="yes"（非布尔）→ 400 含 must be a boolean；随后 GET 复查用户级生效值仍为缺省（未被写入）。出处：core/dashboard/data.py:4704-4718。 | pass | 0/5 | - |
| api-config-project-level-rejected-400 | 项目级写入 self_evolution 被拒（self-evolution spec「项目级写入被拒」）：POST /api/config?project=scheduling-showcase 携带 self_evolution → 400 与可读错误（提示全局用户级键）；复查项目级生效值 auto_accept 仍为用户级缺省 false（项目配置文件未被写入该键）。出处：core/dashboard/data.py:4698-4702；core/dashboard/server.py:2011-2037。 | pass | 0/3 | - |
| web-settings-self-evolution-tab | 设置页「自进化」页签与卡片布局（suggested-improvements-ui spec「页签文案为自进化」「两张卡片按序渲染」）：设置页左侧菜单含「自进化」（不再出现「自愈」），点击后渲染两张卡片——第一张「代码陈旧自愈」（StaleCodeSelfhealPanel）与第二张「建议改进项」（SuggestedImprovementsPanel）。出处：core/dashboard/static/src/pages/settings/index.tsx:24-37,273-289（菜单与面板挂载）；app.tsx:111 路由 /settings。 | pass | 0/6 | - |
| web-stale-code-selfheal-no-regression | 既有自愈面板不回归（stale-code-selfheal spec「页签改名不影响自愈行为」「设置页可读写该节」）：「自进化」页签下第一张卡片控件原样——enabled 开关（data-testid stale-code-selfheal-control-enabled）、连续空闲确认秒数输入（idle_confirm_seconds，本机配置 120）、保存按钮，配置键与缺省语义不变。出处：core/dashboard/static/src/pages/settings/components/StaleCodeSelfhealPanel.tsx:54-117。 | pass | 0/5 | - |
| web-evolution-table-status-mapping | 建议改进项表格状态文案映射（suggested-improvements-ui spec「状态文案映射」「表格列与顺序」）：7 种状态全部渲染为中文文案——待决策/不需要立项/草稿生成失败/已同意/已自动接受/已拒绝/接受失败；表格非空（无空态占位）。出处：SuggestedImprovementsPanel.tsx:289-334（列定义/状态 Tag 映射 EVOLUTION_STATUS_LABELS services/dashboard.ts:869-877）、:373-381（Table locale.emptyText）。 | pass | 0/9 | - |
| web-evolution-drawer-analysis-view | 查看分析结论（suggested-improvements-ui spec「展示分析全文」）：analyzed 条目 E 的操作列「更多」→「查看分析结论」→ Drawer 渲染 analysis_md 全文（含三项判定与「未核实」证据标注）。出处：SuggestedImprovementsPanel.tsx:152-171 openAnalysis、:385-400 Drawer+Markdown。 | pass | 0/4 | - |
| web-evolution-drawer-draft-view | 查看 SPEC 草稿·Proposal（suggested-improvements-ui spec「切换查看四类草稿文档」前半）：pending 条目 B 的操作列「更多」→「查看 SPEC 草稿」→ Drawer 打开并默认渲染 proposal.md 内容。出处：SuggestedImprovementsPanel.tsx:211-220 openDraft（默认 doc=proposal）、:403-436 Drawer。 | pass | 0/3 | - |
| web-evolution-drawer-draft-switch | 查看 SPEC 草稿·四文档切换（suggested-improvements-ui spec「切换查看四类草稿文档」）：打开条目 B 草稿 Drawer 后依次点击 Design/Tasks/Spec 切换按钮，切换不报错且最终渲染 spec.md 内容（四文档内容正确性另由 api-evolution-draft-four-docs 覆盖）。出处：SuggestedImprovementsPanel.tsx:403-436（extra 内四文档 Button、EVOLUTION_DOCS services/dashboard.ts:880）。 | pass | 0/3 | - |
| web-evolution-more-menu-items-order | 操作列「更多」链接按钮交互与菜单四项顺序（suggested-improvements-ui spec「菜单四项与顺序」）：点击 pending 条目 B 的操作列「更多」按钮（antd Dropdown 触发器，Button type="link"），下拉打开并依次渲染「查看分析结论 / 查看 SPEC 草稿 / 同意 / 拒绝」四项。covers 登记 link=tasks.md:100 的 Button type="link"。出处：SuggestedImprovementsPanel.tsx:330-331（Dropdown + Button type="link">更多</Button>）、:58-61（ACTIONS 数组顺序 analysis/draft/accept/reject）、:9 行 Table rowKey="id"→tr[data-row-key]；导航出处 core/dashboard/static/src/app.tsx:111（/settings 路由，hash 路由）。 | pass | 0/7 | - |
| web-evolution-accept-flow | 同意立项完整流（suggested-improvements-ui spec「同意需二次确认」「同意成功刷新与提示」）：pending 条目 B 操作列「更多」→「同意」→ 弹出二次确认 Modal.confirm（标题「同意立项」）→ 点确认（.ant-modal-confirm-btns .ant-btn-primary）→ 真实调用 POST /api/evolution/accept 完成落地（草稿复制 spec/changes/evo-fixture-settings-maxhint + 仅 add 该目录提交 + add_spec drafted/priority=5）→ 成功提示「已立项：evo-fixture-settings-maxhint」且表格刷新后该行状态「已同意」。出处：SuggestedImprovementsPanel.tsx:224-244 handleAccept、:270-285 menuItems；services/dashboard.ts:908-915 acceptEvolutionItem。 | pass | 0/4 | - |
| web-evolution-reject-flow | 拒绝完整流（suggested-improvements-ui spec「拒绝成功刷新与提示」）：pending 条目 C 操作列「更多」→「拒绝」→ 二次确认 Modal.confirm → 点确认（danger 按钮）→ 真实调用 POST /api/evolution/reject 删除草稿并置 rejected → 成功提示「已拒绝」且表格刷新后该行状态「已拒绝」。出处：SuggestedImprovementsPanel.tsx:246-267 handleReject（okButtonProps danger）、:270-285 menuItems；services/dashboard.ts:917-924 rejectEvolutionItem。 | pass | 0/4 | - |
| web-evolution-disabled-analyzed | 无草稿条目禁用规则（suggested-improvements-ui spec「无草稿条目的禁用规则」）：analyzed 条目 E 的「更多」菜单——「查看 SPEC 草稿」「同意」「拒绝」均置灰禁用（ant-dropdown-menu-item-disabled），仅「查看分析结论」可点。出处：SuggestedImprovementsPanel.tsx:64-78 getActionDisabled。 | pass | 0/5 | - |
| web-evolution-disabled-decided | 已决定条目禁用规则（suggested-improvements-ui spec「已决定条目的禁用规则」）：accepted 条目 G 的「更多」菜单——「同意」「拒绝」禁用，查看类（分析结论/SPEC 草稿）保持可用。出处：SuggestedImprovementsPanel.tsx:64-78 getActionDisabled。 | pass | 0/5 | - |
| web-evolution-disabled-draft-failed | 草稿生成失败条目禁用规则（suggested-improvements-ui spec「无草稿条目的禁用规则」扩展）：draft_failed 条目 F 的「更多」菜单——「查看 SPEC 草稿」「同意」禁用，「拒绝」保持可用（可放弃并删除）。出处：SuggestedImprovementsPanel.tsx:64-78 getActionDisabled。 | pass | 0/5 | - |
| web-evolution-empty-state | 空态（suggested-improvements-ui spec「空态」）：项目级作用域切到 fenix-server（夹具无该项目的条目，items?project=fenix-server 返回空）→ 表格区域显示空态文案「暂无建议改进项」而非空白或报错。出处：SuggestedImprovementsPanel.tsx:371-382（locale.emptyText='暂无建议改进项'）；loadItems 按 project 过滤 services/dashboard.ts:885-889。 | pass | 0/3 | - |
| web-suggested-config-user-scope-save | 用户级作用域配置保存往返（suggested-improvements-ui spec「用户级作用域读写往返」前半）：用户级作用域把「每轮分析条目上限」改为 25 保存 → POST /api/config（不带 project，写用户级）→ 成功提示「保存成功」→ 表单回显 25。出处：SuggestedImprovementsPanel.tsx:102-112 handleSaveConfig（onSave 不带 project）、:352-365；settings/index.tsx:99-113 handleSave 保存后重读配置回显。 | pass | 0/4 | - |
| web-suggested-config-user-scope-restore | 用户级配置还原（配套恢复场景，避免污染运行时配置）：把「每轮分析条目上限」改回缺省 20 保存 → 回显 20，机器配置恢复缺省。出处：同 user-scope-save。 | pass | 0/4 | - |
| web-suggested-config-project-scope-readonly | 项目级作用域只读提示（suggested-improvements-ui spec「项目级作用域只读提示」）：切到项目级作用域（scheduling-showcase）后，「建议改进项」卡片顶部开关与上限输入置为只读（ant-switch-disabled），显示「全局键…请在用户级作用域修改」提示，且不再渲染保存按钮（MUST NOT 允许在此作用域提交 self_evolution）。出处：SuggestedImprovementsPanel.tsx:340-365（isUserScope 分支 + Form disabled）。 | pass | 0/5 | - |
| web-evolution-mobile-scroll-fixed | 移动端横向滚动 + 操作列固定（suggested-improvements-ui spec「移动端可横向滚动且操作列固定」）：390×844 视口下设置页以移动布局渲染（横向菜单），「建议改进项」表格列超出容器宽度可横向滚动，操作列以 fixed right 渲染（th.ant-table-cell-fix-end 存在）。出处：SuggestedImprovementsPanel.tsx:320-333（fixed: 'right'）、:378（scroll x:800）；settings/index.tsx:146-171 移动端菜单横排。 | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 42 个（第 1 轮）。

首轮写入 42 个场景

