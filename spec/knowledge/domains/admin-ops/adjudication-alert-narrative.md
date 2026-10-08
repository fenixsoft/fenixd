# 转人工裁决告警调查叙事

<!-- knowledge: capability=adjudication-alert-narrative rev=2
     sources=spec/archive/2026-10-06-add-adjudication-alert-narrative,spec/archive/2026-10-09-upgrade-narrative-to-investigation -->

转人工裁决告警的人类可读调查层：告警先以机械文案立即落盘，LLM 在后台采集验证产物证据并生成四段式调查叙事（发生了什么 / 调查结论 / 为什么需要你决策 / 决策选项），经侧车文件异步补写——决策者读告警即可获得有据的根因判断，无需另行询问。

## 规则

- 适用范围：携带 `choices` 的桶 2 真裁决信号写告警时生成叙事；桶 0 知情/自愈类信号（choices 为空）不发起叙事调用。叙事是纯增强内容：不改写 description/evidence/recommended_action/choices/trigger 任一字段的结构化语义，机器消费方（alert-resolve、闭环判定、Administrator 处置）零感知，不参与动词分派与闭环判定。
- 四段固定结构：叙事为 Markdown，段落标题逐字固定且顺序不可变——「发生了什么」「调查结论」「为什么需要你决策」「决策选项」。机械校验要求四段齐全且顺序不倒置，缺段（含仅输出三段）、倒置一律判失败走兜底。「发生了什么」把技术串翻译为因果白话并指明信号主体；「调查结论」必须基于【验证材料】给出根因判断并引用具体证据（计数器/预算/环境事实）；「为什么需要你决策」说明自动链已尝试的路径、停止原因与放任继续的代价；「决策选项」对 choices 快照逐 id 给出含义、后果与参考倾向（倾向为参考，最终由人决定）。反编造三句式：材料内有据可依的因果推断必须给出、材料外事实不得编造、材料不足以定位时必须明写「材料不足以定位」并给出建议查证路径。
- 证据采集按 signal_type 注册：验证族信号（judge_rerun_cap / inconclusive_loop / verdict 相关预算与闸门族）通用采集四产物——`spec/changes/<spec>/verification-report.md` 全文、`.fenix/verify-progress/<spec>/report.json` 的 summary 与失败/警告场景表（含 classification 分布）、同目录 `verdict_stability.json` 的判定轮次历史、`fail_history.json` 的轮次演进。采集 fail-open：任一文件缺失/损坏跳过该段不阻断生成；非验证族信号不注入材料段。总上下文预算 16K 字符分段截断（段界保留、截断标记标注）。
- 发射点可选注入 `facts` 结构化字段（如 judge 派发台账等内存中独有、事后难重建的信息），存在时注入 prompt，缺省不注入不破坏。
- 异步补叙零阻塞：告警发射点以机械文案立即落盘，落盘耗时不含 LLM 时延；叙事后台生成，完成后经原子写（mkstemp + os.replace）补写到独立侧车 `.fenix/admin_alerts_narrative/<alert_id>.json`（结构 `{"alert_id","text","model","at"}`）。`admin_alerts.json` 记录本体 append 后不可变、不写 narrative 字段；Dashboard 读侧按 alert_id 合并侧车 narrative 字段渲染（text/model/at 形态不变）。
- 有界尝试：单条告警至多 2 次生成尝试，单次受 `admin.narrative_timeout_seconds`（int，缺省 180）硬超时约束；2 次全败写 WARNING 后放弃，不做重试风暴。
- 终态侧车防假态：2 次全败、或熔断生效期跳过生成时，必须写终态侧车（同目录同结构，`text` 为机械说明、`model` 为 null）——失败/跳过的告警不得以「调查生成中」悬挂；读侧「生成中」判定即侧车文件缺失，前端仅对未 handled 且侧车缺失的告警显示「调查生成中」占位，已 handled 无侧车不显示占位。
- 连续失败熔断：生成失败（超时/空输出/结构校验失败）按滑动窗口连续计数，连续 3 次失败即熔断，冷却窗口 1 小时内新告警跳过生成（零 LLM 调用零延迟）；冷却期内零调用、不存在「期间成功」复位路径，到期恢复尝试后一次成功即清零计数；熔断生效与解除均 WARNING 留痕。熔断计数与冷却存 daemon 进程内不持久化，重启即复位。`admin.narrative_enabled=false` 时熔断器与生成整体旁路（零调用零侧车，行为与无叙事基线一致）。
- 历史完整性：人工已处置（handled）后补叙照常落盘并合并渲染，处置流程不受影响。
- 侧车生命周期：告警清理路径（保留上限裁剪等）级联删除对应侧车文件防孤儿堆积；归档视图不含叙事属预期（侧车只服务活跃告警集），渲染按 alert_id 匹配不到的残留侧车忽略即无害。
- 覆盖面单源：全部桶 2 发射点——汇聚写入口 `pm_engine._send_human_escalation_alert` 与两个旁路 choices 附带点（mergeback 的 build_artifact_paths_missing、token_budget）——共享同一叙事辅助模块单源入口，禁止内联第二套生成逻辑或第二套 prompt。
- kind 口径分侧：汇聚点与 token_budget 记录为 kind=ESCALATION，进前端告警区渲染叙事；build_artifact_paths_missing 记录为 kind=SIGNAL，不进前端告警区，叙事仅字段落盘供消费侧读取。
- LLM 通道与配置：经既有 agent spawn 通道非交互单发（带硬超时），不直连网关 HTTP、不引入第二套凭据/UA/代理面；通道依赖注入可替换，测试注入假通道不真调网关。配置三键（admin 段，设置页 SystemPanel 可编辑、热更新生效）：`admin.narrative_enabled`（bool，缺省 true）、`admin.narrative_timeout_seconds`（int，缺省 180）、`admin.narrative_model`（str，缺省空=回退 `admin.agent_model`，仍空=复用框架默认模型）。pm_engine 侧读取统一走 `ConfigLoader.get_admin_config(...)` 取 `narrative_*` 键，不反向导入 dashboard data 层私有缓存函数。
- 前端渲染：narrative 渲染于 evidence 上方，Markdown、默认展开，四段标题依次可见并带「AI 生成」标注；机械字段（描述/证据）照常可见、不遮挡 choices 操作区；无侧车且未 handled 显示「调查生成中」占位，其余形态与无叙事基线一致（无空壳区块）。

## 溯源

- 2026-10-06 add-adjudication-alert-narrative（spec/archive/2026-10-06-add-adjudication-alert-narrative） — 新增本能力：写入口+旁路点全覆盖接线、三段结构契约与 fail-open 兜底、三配置项与告警区渲染
- 2026-10-09 upgrade-narrative-to-investigation（spec/archive/2026-10-09-upgrade-narrative-to-investigation） — 三段升级为四段并引入按 signal_type 证据采集（16K 预算、fail-open）；同步生成改为机械文案即时落盘 + 侧车异步补叙（超时 180s、至多 2 次尝试）；新增连续失败熔断、终态侧车防悬挂假态、清理级联删除
