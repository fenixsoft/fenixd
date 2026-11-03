# 处置链重设计：runner→Admin→Arbiter→人工 + harness 默认 key 回落（开箱即用）

- 日期：2026-11-03
- 状态：设计定稿（brainstorm 收敛），待评审与立项
- 起因：2026-11-02 dsh-plugins 两条人工告警取证（见「背景」）+ 用户对告警处理链的重新定调

## 背景

2026-11-02 dsh-plugins daemon 两条人工告警（`inconclusive_loop` major / `warning_stale_triage` critical）取证发现三个结构性问题：

1. **Arbiter 触发面是白名单**（`core/pm_engine/arbiter.py:77` `ARBITER_TRIGGER_SIGNAL_TYPES`，10 种信号），`inconclusive_loop`/`warning_stale_triage` 结构性不走 Arbiter，直接落人工队列——同因链第三条 `verify_env_blocked` 走了 Arbiter 又因 provider 链缺失秒败（0.001s/0 tokens），转 Administrator 才闭环。
2. **Arbiter/Administrator 车道无 `agents.models` 分配时无法启动**：dsh 适配器要求 provider 链三要素显式渲染（`dsh_adapter.py:731` 预检 fail-fast），arbiter 代码只钉 model 不产 baseurl/apikey，全仓（全局 + 各项目 config）均无 `agents.models.arbiter` 分配 → Arbiter 形同虚设。Knowledge-Distiller 能无分配工作纯因车道硬编码 claude 适配器（环境继承），不是通用回退机制。
3. **闭环缺口**：原始 escalation 告警无 `admin_run_id`/`trigger` 字段，Administrator 处置成功后 `close_escalations_for_run`（按 admin_run_id 关联）与 auto-resolve（按 trigger）都关不掉 → 已解决事故的告警永久滞留人工队列（11-02 两条即此形态）。

用户对告警处理链的重新定调：**人工裁决从「默认终点」降级为「例外出口」**。

## 目标

- 全部升级边信号默认走自动化处置链（Admin → Arbiter），人工只在两级自动化都失败后出场。
- 人工出场即带完整背景：Admin 尝试痕 + Arbiter 调查台账五段 + 剩余 choices。
- 任一 Agent（不限于 Arbiter）无 `agents.models` 分配时**开箱即用**：回落 harness 自己配置的 key。
- SPEC 运行时间轴中，链上各角色（Admin/Arbiter）的处理记录与其他 Agent 一样作为一等节点可见。

## 非目标

- 不改动各信号既有的自愈/重试梯子（transient backoff、verify 自动重验、severity 批闸、同因重派熔断等）——它们定义「runner 自修复何时算耗尽」，本设计只改耗尽那一刻的去向。
- 不合并 Admin 与 Arbiter 车道，不改动两车道自身的 run 机制（预算封顶、单飞队列、处置包注入形态）。
- 不改动 Knowledge-Distiller 等既有硬编码 claude 的旁路车道。

## 反目标（出现即算失败）

- 人工队列再次出现「底层已解决但仍 pending」的过期告警（11-02 形态）。
- 自动化链成为黑箱：时间轴/处置链视图看不到链上正在发生什么。
- Arbiter/Admin 失联导致告警丢失：任何失能形态必须 fail-open（降级直达人工，绝不静默吞信号）。

## 处置链（用户定调）

```
信号升级边触发（既有自愈/重试梯子耗尽的那一刻）
   ↓
① Admin 车道 —— 标准环境运维（受限工具 + 只见当前 run 注入结果的安全修复面）
     ├─ 处置成功 → 闭环，人工零感知
     └─ 处置失败 / 自判超范围（不计失败）↓
② Arbiter 车道 —— 全局视野，交人工前最后一道防线
     ├─ 拍板成功 → 闭环，人工零感知
     ├─ 复现配额：同签名拍板 2 次，第 3 次复现 ↓
     └─ 自判无法处理 / 尝试无效 / run 崩溃超时（沿用现有失败重试 1/2 次）↓
③ 人工队列 —— 告警 + Admin 尝试痕 + Arbiter 台账五段 + 剩余 choices
```

## 用户决定（定稿依据，实现不得偏离）

1. **开箱即用 key 回落**：没有为任何 Agent 分配 key 时，使用 harness 自己配置的 key。全局 `agent.harness` 已切 `claude`（`~/.fenix/config.yaml:278`），各项目 config 未覆盖。
2. **人工不可见中间态**：Admin/Arbiter 处理中的告警不进人工队列；只有经过 Arbiter 处理且失败的告警才上升人工。
3. **黑名单清空**：原排除表 5 个信号（`impl_budget_exhausted`、`impl_budget_exempt_loop`、`spec_content_missing`、`spec_delivered_no_content`、`redispatch_loop_detected`）全部交由 Arbiter 尝试处理；预算类 Arbiter 可拍板 2 次「继续烧」，第 3 次复现上升人工。
4. **失败双轨定义**：(a) Arbiter 自判无法处理、无法做出决策，或尝试处理后不成功；(b) 同一问题 Arbiter 处理 2 次仍复现。
5. **Admin 车道保留且居 Arbiter 之前**：受限工具、受限视野（只能看到当前 run 注入的结果）下的安全修复，是 Arbiter 登场前的标准环境运维角色。链序：runner 无法自修复 → 呼叫 Admin → 上升到 Arbiter → 上升到人类。
6. **时间轴可见性**：SPEC 运行时间轴中 Arbiter 的处理记录与其他 Agent 一样可见（Admin 同理）。

## 默认决定（my call，评审/用户可推翻）

1. **Admin 尝试配额同为 2 次/签名**（run 崩溃/超时计一次尝试；Admin 自判「超范围/非环境问题」转 Arbiter 不计失败），与 Arbiter 配额对称。
2. **复现计数复位**：签名连续 7 天无复现清零，或该 spec 状态发生迁移（如 blocked→ready）清零。
3. **排除表机制保留、初始为空集**：作为线上 kill switch（热加信号名即绕过全链直达人工）；`arbiter.enabled=false` 或 Admin+Arbiter 双双失能时整体退回现状行为（升级边直达人工队列）。
4. **narrative 车道保留为降级兜底**：正常路径升级件的叙事由 Arbiter 台账承担（联查机制已有）；双车道关闭的降级态仍用 narrative 补叙。
5. **Dashboard 交付项**：新增「自动化处置链」视图（Admin/Arbiter 在办与队列状态、配额水位可见；人工队列只显失败上升件）+ 新配置项（两级配额、复位窗）的设置界面——遵循「新增配置必须带 Dashboard 界面」项目惯例。
6. **回落告警面**：无分配回落 harness 默认 key 时发一次 WARNING + 事件留痕（不拒 spawn）——10-09 CLI 默认档别名拒识教训仍在，留观察钩子；model 维持各车道现有钉死默认值（钉死值本身即零配置开箱值）。
7. **降噪分级废止（链入口不按 severity 过滤）**：原「仅 critical/major 进人工队列，warning/minor 写入即静默」（2026-09-01 决策）的前提是处置成本=人工注意力；链上成本变为 Admin/Arbiter run 后理由消失，且用户点名的 5 信号含 minor 级（`impl_budget_exempt_loop`）。原降噪仅在降级态（fail-open 直达人工）保留，避免降级时人工队列被 warning 刷屏。

## 链语义细则（评审问题定案，2026-11-03 builder check 后补）

1. **自环防线——链入口按信号来源判定**：链入口只收「框架/runner 侧产生的升级边信号」。链成员的处置输出永远是链内转单边（Admin 超范围→转 Arbiter、Admin/Arbiter 失败→下一级），不作为新信号重新入链。`manual-intervention` 族语义随之收编：Admin 的转单对象改为 Arbiter，「转人工」仅存在于链终点；恢复期 `human_alert_callback` 属框架信号，正常入链头。`admin_dispatch_programming_error` 等框架自指类照常入链（Arbiter 具备立项修框架的通道，修不动即人工）。
2. **闭环定义**：链内任一级「处置成功」的终态收口必须同时完成两件事——告警/信号收口 **+ spec 状态恢复可运行**（框架侧 side-effects，沿用 Arbiter `_apply_disposition_side_effects` 纪律：显式 status、拒绝 parse 兜底）。Admin 车道获得与 Arbiter 同型的框架侧 side-effects 执行路径（防「告警闭环但 spec 永久 frozen」楔死变体）。
3. **链头派发机制**：事件驱动直派——对齐 Arbiter lane 单飞队列形态（同签名 dedup + 复用在飞互斥守卫 + 队列深度上限），不走 admin_monitor 5 分钟巡检（巡检延迟与 backoff 会吃满两级链延迟）。admin_monitor 保留既有兜底看护：pending 超时升级语义不变，看护对象扩展为全链在办件。
4. **Admin 超范围的机器可读通道**：disposition 产出新增结构化字段（`handoff: arbiter` + `handoff_reason`），不重载 `result=escalate`（现语义「需人工决策」的既有消费者不破坏）；Administrator prompt 契约段同步更新（改 prompt 先 merge main）。
5. **既有「同签名只自主处置一次」纪律（D6）被新配额制正式取代**：`_dispositioned`/`_ledger_sigs` 的永久跳过与回扫排除逻辑随配额状态改写（相关机械守卫测试同步改写）。例外：dead-man/停机类基础设施死亡签名维持永久单次、不适用 7 天复位（反复停机是工程问题，不是可反复拍板的运营决策）。
6. **dsh harness 形态的回落（2026-11-03 用户裁定，推翻本文件初版「车道失能」判定）**：回落语义对 harness 对称——dsh 适配器无分配时**省略 `--patch`**，由 dsh 按 profile 自身配置的默认模型启动（「dsh 本身配了模型就用 dsh 的」），与 claude 的环境继承/CLI 默认档完全同构；不再强制预检 fail-fast。归因降级对称接受（provider=null + `harness-default` 标记，观察钩子补齐）；dsh 自身也未配置模型时属 harness 级失败，走既有失败轨（不预检拒绝）。反串扰的 `ANTHROPIC_*`/`CLAUDE_*` 环境清除与此无关、照旧保留。
7. **spec=null 信号的签名粒度**：签名遵循用户「同一个问题」语义——主体键优先（从信号 payload 提取：蒸馏欠账的归档名、triage 的场景集指纹等），提取不到主体时退化为类型级并在台账标注粒度。
8. **存量 pending 告警迁移**：上线时一次性迁移——能判定「底层已闭环」（同签名 spec 已终态/处置已 resolved）的自动收口（附 `close_cause=migrated`），其余留人工一次性清理；不回填入链（旧问题不烧新链配额）。

## 实现面映射（关键落点）

| 现状 | 落点 | 变更 |
|---|---|---|
| 升级发射咽喉落人工 | `core/pm_engine/family.py:1587` `_send_human_escalation_alert`；freeze_for_human 双咽喉 | 改道：默认派发 Admin（入链头）；人工队列写入仅在 Arbiter 失败上升时发生，上升件天然携带 Admin/Arbiter 关联键（修 11-02 闭环缺口） |
| 白名单触发面 | `core/pm_engine/arbiter.py:77`（白名单 10 信号）、`:101`（排除表 5 信号）、`core/adjudication_narrative.py:81` `narrative_yielded_to_arbiter` | 触发面反转：默认全入链，黑名单配置化（初始空）；让位判定方向反转 |
| Arbiter 让位判定 | `narrative_yielded_to_arbiter` 三条件（enabled/触发面/可装配） | 改为链头派发判定（Admin 在前）；降级路径保留 narrative |
| provider 链预检 | `core/agent_runner/harness/dsh_adapter.py:715-735`（三要素 fail-fast）；`claude_adapter` 环境继承 | 「无分配=合法态」且两 harness 对称：claude 缺分配=环境继承/CLI 默认档；dsh 缺分配=省略 `--patch` 按 profile 默认档启动（归因降级 provider=null+`harness-default` 标记）；`agents.models` 校验放宽；WARN+留痕对称适用 |
| Arbiter 钉死模型 | `core/pm_engine/arbiter.py` `ARBITER_PINNED_MODEL`（「MUST NOT 回落默认档」D9 决策） | 语义修正：钉死值=未分配时的开箱默认 model（不再是「禁止回落」），分配存在时用分配值 |
| 预算拍板权 | `core/pm_engine/budget.py`（`impl_run_budget_override` 等 spec 字段；豁免现依赖人工/override 配置） | Arbiter 新动作面：落预算豁免（写 override 字段 + 台账留痕）；Admin choices 白名单不含预算/豁免类 |
| Admin 处置面 | `core/dashboard/data/adjudication_choices.py` choices 注册表；admin run 处置包 | 明确 Admin 拍板面=注册表的环境运维子集；超范围自判转 Arbiter |
| 失败重试 | arbiter 同签名失败重试（1/2 次）+ 半成品调查包升级 | 保留，作为失败轨 (a) 的组成部分 |
| 签名键 | `arbiter_failure_signature`（`spec::signal_type`） | 复用为两级配额/复现计数的键 |
| 时间轴联查 | `core/dashboard/data/timeline.py:200` `_arbiter_ledger_index`、`:252` `_arbiter_node_payload`（add-arbiter-quality-display 已交付） | 扩展：Admin 尝试、Arbiter 每次尝试（含配额计数/复现事件）、最终上升件均入时间轴；非 spec 信号（spec=null，如蒸馏重试欠账）落处置链视图 |
| 人工队列口径 | `core/dashboard/data/admin_alerts.py:69` `_unhandled_records`（kind=escalation 且未 handled） | 口径不变，但队列内容变为「仅失败上升件」 |
| 闭环收口 | `core/admin_store.py:995` `close_escalations_for_run`；alert_lifecycle auto-resolve trigger | 上升件携带全链关联键；链上任一级成功闭环时自动收口上升件（若已在队列） |

## 约束（不得破坏的既有机制）

- 信号既有自愈/重试梯子逐字节保留（含 code-fix 停链判据、severity 批闸、扫描节律）。
- Admin 在飞互斥守卫（bc3c07e8 家族，跨类型双重派发修复在途）——Admin 派发必须走既有互斥语义。
- Arbiter 单飞队列深度上限（`ARBITER_QUEUE_MAX=8`）与立项节流三限（`PROPOSAL_MAX_PER_RUN`/`PROPOSAL_WEEKLY_QUOTA`）保留；同签名 dedup 防重复派发。
- 全链时间戳 UTC 单一后缀族；配置 30s 热更新生效；新增配置项必须带 Dashboard 界面。
- 台账五段结构键（scene_snapshot/forensic_timeline/root_cause/action_or_upgrade/evidence_refs）不变。
- 降级路径（双车道失能/`arbiter.enabled=false`/kill switch 命中）行为与合入前逐字节一致（对齐「关闭态零侵扰」s8 惯例）。

## 留给实现者的开放点

- 复现计数的存储位置：arbiter ledger 扩展字段 vs 新 state 文件（建议后者：计数是状态不是台账事实）。
- Admin→Arbiter 转单的载荷形态：Admin 尝试痕（run 摘要/失败原因）如何注入 Arbiter 调查 prompt。
- 上升件 choices 的快照时序：上升落盘时快照 vs 前端动态取注册表。
- 链队列溢出（>8）时的降级动作（建议：最旧低severity 件直达人工并告警容量）。
- minor/warning 信号入链后与 Admin `interval_minutes: 5` 节流的相互作用（同签名 dedup 窗口是否需要独立配置）。

## 验收场景（最小集）

1. 升级边信号触发 → Admin 接单（人工队列零痕迹）→ Admin 修复成功 → 闭环，时间轴可见 Admin 节点，人工队列始终为空。
2. Admin 2 次失败 → Arbiter 接单 → 拍板成功（如预算豁免）→ 闭环，台账+时间轴可见，人工队列始终为空。
3. Arbiter 拍板 2 次后同签名第 3 次复现 → 上升人工，告警附全链痕迹与 choices；人工处置后闭环收口。
4. Arbiter run 崩溃 → 同签名重试 1/2 → 仍败 → 上升人工（半成品调查包附上）。
5. 无 `agents.models` 分配的项目：Admin/Arbiter spawn 成功——claude 回落环境继承/CLI 默认档，dsh 省略 `--patch` 按 profile 默认档；两形态均 WARN 留痕一次，metrics 归因降级带 `harness-default` 标记。
6. kill switch / `arbiter.enabled=false`：行为与合入前逐字节一致（升级边直达人工队列，narrative 补叙）。
7. SPEC 时间轴：上述各场景的 Admin/Arbiter 节点均可见且台账联查命中；非 spec 信号在处置链视图可见。
8. 链成员不自环：Admin 处置中产出「超范围」转单直达 Arbiter（不重入链头、不计失败）；框架自指类信号（如 `admin_dispatch_programming_error`）正常入链头。
9. 链级对称回落：claude 与 dsh 两 harness 在无分配时均开箱 spawn 成功（各自回落自身默认配置）；dsh 自身也未配置模型时走既有失败轨（不预检拒绝），WARN 与失败证据可归因。
