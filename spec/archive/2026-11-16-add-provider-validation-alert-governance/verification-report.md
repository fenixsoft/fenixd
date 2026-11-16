# 验证报告：add-provider-validation-alert-governance

> ⚠️ 本报告由框架于 2026-11-08T12:52:54Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-08T12:52:53.875812+00:00+run-result@mtime1794142373923066185

## 结论：✅ 通过（verified）

**状态：verified — 15/15 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 15/15 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 13.30M |
| 本链增量 Token（输出） | 0.23M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| provider-load-unregistered-alert-suggestion | 加载路径 provider 引用校验（D1/D2/spec 场景「未注册 provider 触发告警而非静默跳过」＋「一字之差给出即修建议」）：临时项目 config.yaml 以 implementer.provider=bigmodel.cn 引用未注册名（注册表仅 bigmodel-cn），ConfigLoader.resolve_config 加载后必须产生一条 major 配置告警（cause=model-chain，文案含角色名、未注册名、相似名建议「是否意指 bigmodel-cn」与修复指引），不再静默跳过；同指纹二次加载去重不重发；修复后指纹消失自动复位、再改坏告警再产生。探针在 /tmp 临时项目内进程内驱动，产物断言走 AdminStore 读侧。judge 原地修复（2026-11-08）：注册表条目补 model 使 BAD 夹具唯一缺陷为未注册引用；fixed_no_alert 改按单测口径（相关记录 handled=自动复位 + unhandled 清零），原计数等式与自动复位语义自相矛盾。 | pass | 0/10 | - |
| provider-load-legal-ref-zero-change | 合法引用零行为变化回归（spec 场景「合法引用零变化」）：全部 provider 引用已注册时 resolve_config 加载零新增告警，get_agent_model_assignment 链解析与引入前一致（2 元素链、链首 bigmodel-cn）；verifier 角色无 models 条目保持「无分配」回落语义（返回 None），无新增告警。 | pass | 0/4 | - |
| provider-chain-invalid-assignment-no-fallback | 「无分配」与「分配失效」划界（D3/spec 场景「分配失效不静默回落」）：implementer 与 verifier 两角色均有 models 条目但全部引用未注册名——加载后发配置告警且 evidence 保留原始链条目（含 bigmodel.cn）；链解析结果必须与「无分配」（None，回落形态）可区分（get_agent_model_assignment 不返回 None），即分配失效态不得静默走 harness-default 回落。judge 原地修复（2026-11-08）：划界口径改调 get_agent_chain_resolution（D3 判定单源，status=invalid/unassigned），并补 unassigned_contrast 对照；get_agent_model_assignment 对失效链返回 None 属既有运行期语义。 | pass | 0/6 | - |
| dashboard-save-path-reject-suggestion | Dashboard 保存路径拒绝语义与相似名建议两路径同源（D1/D2/spec 场景「一字之差给出即修建议」＋「无相似项时给注册表清单」）：POST /api/config（校验失败 400 拒绝、不落盘，patch 体自带 agents.max_concurrent=-1 兜底守卫确保任何回归下都不会误写用户级配置）。请求一：注册表 [bigmodel-cn, zhipu-src]、引用 bigmodel.cn → 400 且报错含「引用了不存在的 provider」既有文案与「是否意指 bigmodel-cn」建议；请求二：引用 nonexistent-llm（无相似项）→ 400 且报错列出注册表全部已注册名。出处：core/dashboard/routes/base.py:672、core/dashboard/routes/settings_routes.py:139、core/dashboard/data/config_admin.py:2575。judge 原地修复（2026-11-08）：body 由对象字面量改为 json.dumps JSON 字符串（引擎 http_request 期望字符串形态请求体）。 | pass | 0/7 | - |
| provider-ref-validation-unit-tests | 交付单测门（tasks 1.4）：tests/test_provider_ref_validation.py 全量通过——未注册引用告警、相似名建议、合法引用零变化、指纹去重与复位、Dashboard 保存路径拒绝回归、两路径规则同源。pytest 仅用 -v（禁 -q，防 PASSED 退化）；exit_code=0 仲裁全绿。 | pass | 0/3 | - |
| contract-precheck-implementing-info-once | 实现期契约预检降级与一次性（D4/spec 场景「实现期单条 info 不召唤」）：临时项目 .fenix/verify.yaml 为全注释模板态（contract_file_unresolvable=True）、spec 处于 implementing，AdminMonitor._detect_verify_contract_unresolved 首轮只发一条 info 级信号且文案保留「勿复位」实现期指引；同实例二次巡检零信号；重新实例化（模拟重启、去重态持久化随告警账本）仍零信号。judge 原地修复（2026-11-08）：探针补 _handle_signal 入账（去重判据持久化于账本 store.has_unhandled_signal，直调探测不入账则去重态永不建立）。 | pass | 0/5 | - |
| contract-precheck-testing-restore-major | 进入验证阶段后恢复 major 语义（D4/spec 场景「进入验证阶段后恢复 major 语义」）：同一临时项目先以 implementing 触发 info 一次性去重，随后 spec 状态迁移为 testing（离开实现流程，去重态复位）且契约仍未裁决——预检恢复既有 verify_contract_missing major 语义发信号。 | pass | 0/3 | - |
| contract-precheck-adjudicated-zero-signal | 契约已裁决零信号（D4/spec 场景「契约已裁决零信号」）：.fenix/verify.yaml 为可解析契约态时，implementing 与 testing 两状态下预检均不发任何 verify_contract_missing 信号（实现期 info 与验证期 major 都不发生）。 | pass | 0/3 | - |
| contract-precheck-noise-unit-tests | 交付单测门（tasks 3.2）：tests/test_contract_precheck_noise.py 全量通过——实现期单条 info 不召唤、状态迁移后恢复 major、契约已裁决零信号、重启不重发。pytest 仅用 -v（禁 -q）；exit_code=0 仲裁全绿。 | pass | 0/3 | - |
| alert-supersede-unit-tests | 交付单测门（tasks 4.4/4.6）：tests/test_alert_supersede.py 全量通过——观测点触发批量失效原子性、观测点不全不触发、既有终态路径（auto-resolve/self-heal/人工 close）不受影响、撤销 supersede、unknown 根因不参与自动失效、存量账本 cause 回填与 unknown 豁免。pytest 仅用 -v（禁 -q）；exit_code=0 仲裁全绿。 | pass | 0/3 | - |
| seed-alert-fixtures-for-panel | 面板场景夹具供给（前置）：经 AdminStore 真实通道向验证实例自身项目（cwd=验证树根，非 fixture 打标、进缺省跨项目聚合）写入 5 条 escalation 种子——3 条未处理（2 条 cause=model-chain、1 条 cause=harness-cli，description 不含根因词避免断言自证）与 2 条 cause=model-chain 的 superseded 已失效记录（handled_by=superseded，resolve_note 含「模型链修复观测点通过」）。幂等可重入（按 description 去重）。judge 原地修复（2026-11-08 二轮）：种子落在真实实例账本上、两轮间被实例自身告警收口链逐条收走（mark_handled 形态：handled=True 且 handled_by/close_cause 皆空，非本特性 supersede 观测点——刻意失效种子 superseded 计数未动），原幂等只保存在性不恢复未处理态致重入失配；新增恢复段经 update_records 重置 3 条未处理种子的未处理态（不触碰刻意失效种子与非种子记录），断言与计数口径不变。 | pass | 0/4 | - |
| alert-panel-superseded-collapsed-group | 面板「已失效」折叠组与未处理计数（tasks 4.3/spec 场景「模型配置修复后旧告警批量失效」的呈现面）：overview 告警横幅未处理计数为 3 条（2 条 model-chain + 1 条 harness-cli 种子，superseded 不计入）；未处理列表可见 model-chain 种子；「已失效 (2)」折叠组默认收起（组内已失效种子在 DOM 不可见＝不计入未处理的机械证明）；展开后已失效种子与其触发观测点记录（模型链修复观测点通过）可见，且存在人工撤销 supersede 恢复未处理入口（「恢复未处理」）。出处：http 路径来自 core/dashboard/static/src/app.tsx:146（SPA /overview 路由）与 core/dashboard/static/src/pages/overview/components/AlertBanner.tsx（横幅/展开列表/折叠区真实结构）；「已失效」「恢复未处理」文案为 spec alert-lifecycle ADDED Requirements 4.3  mandate，实现须以此措辞对齐。judge 原地修复（2026-11-08）：横幅 useState(true) 默认展开（展开控件实文「收起列表」）；「已失效」折叠组实现在 activities 页（Collapse defaultActiveKey=['resolved'] 已失效默认收起），overview 横幅只渲染未处理列表——步骤/断言按实面重排，横幅侧以计数 3+已失效种子不在横幅 DOM 承接「superseded 不计入未处理」机械证明。 | pass | 0/8 | - |
| alert-panel-cause-badge-visible | 根因分组呈现（tasks 4.3「根因分组过滤」的可见面）：展开未处理列表后，告警条目按根因标签呈现——model-chain 以「模型链」面呈现可见（种子 description 特意不含根因词，命中只能是根因标签/分组控件本身）。出处：core/dashboard/static/src/app.tsx:146、AlertBanner.tsx；根因中文面措辞以 cause=model-chain→「模型链」为基准。judge 原地修复（2026-11-08）：同 S5：横幅默认展开（useState(true)），展开控件实文「收起列表」；根因标签经 alert-shared AlertTitle「根因：模型链」（data-testid=alert-cause-tag）在横幅未处理条目内呈现，断言随目标面修正。 | pass | 0/4 | - |
| alerts-api-cause-field-contract | cause 根因标签经告警数据链可见（spec alert-lifecycle「入账带根因标签」的读侧契约）：GET /api/alerts 缺省跨项目聚合返回 200，未处理条目携带 cause 字段（种子 harness-cli 记录的根因值经端点透出），severity=major 随条目透出。出处：core/dashboard/routes/alert_routes.py:116（/api/alerts 缺省聚合分支）。judge 原地修复（2026-11-08）：缺省聚合响应体 >64KB（引擎 _JSON_PARSE_LIMIT，超限 resp_json=None），json_path/json_schema 对此端点结构性不可跑——severity 透出断言改 body_contains 紧凑序列化形态 "severity":"major"（种子按 created 倒序居响应最前，必然命中）。 | pass | 0/4 | - |
| alert-panel-undo-supersede-restore | 人工撤销 supersede 恢复未处理（tasks 4.3「人工撤销 supersede 恢复未处理入口」）：在已展开「已失效」组的横幅内点击首条已失效告警的「恢复未处理」→ 该告警回到未处理态：横幅未处理计数 3→4、「已失效」组计数 2→1，恢复件与剩余失效件同时可见（步骤窗口内应伴随告警数据重拉）。出处：core/dashboard/static/src/app.tsx:146、AlertBanner.tsx；「恢复未处理」为撤销入口措辞（spec alert-lifecycle 4.3）。judge 原地修复（2026-11-08）：撤销入口实为 activities 页「撤销失效」按钮（data-testid=alert-revert-supersede → /api/alerts/<id>/revert-supersede），横幅与折叠组分属两面且断言须单页收口——「3→4 条未处理」以「已失效 (1) 组计数 + 恢复件入未处理列表」等强度机械证明承接。judge 原地修复（2026-11-08 二轮）：dashboard 为 hash 路由（config/config.ts history:hash），告警折叠组挂 activities「告警记录」页签（initialTab 按 location.hash 的 ?tab= 预选、缺省处置链）——裸路径 /activities 未预选页签致 text=已失效 不在 DOM；navigate 改 hash 深链 /#/activities?tab=alert。 | pass | 0/7 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

