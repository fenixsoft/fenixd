# 主树散件 WIP 周期盘点与滞留升级

<!-- knowledge: capability=maintree-stray-wip-sweep rev=9
     sources=spec/archive/2026-10-08-evo-add-maintree-stray-wip-sweep,spec/archive/2026-10-09-evo-add-maintree-interactive-session-attribution,spec/archive/2026-10-26-evo-add-commit-stray-wip-choice,spec/archive/2026-10-27-evo-recurring-stray-remediation,spec/archive/2026-10-30-evo-maintree-stray-attribution-log-dedup,spec/knowledge/_inbox/done/dsh-session-gap-in-maintree-wip-attribution.md,spec/knowledge/_inbox/done/2026-11-16-maintree-stray-sweep-refire-noise.md,spec/changes/evo-persist-stray-tracked-registry,spec/knowledge/_inbox/done/maintree-stray-wip-attribution-release-exit-commit-over-zero-touch.md -->

daemon 周期只读盘点主树流水线外的 tracked 未提交改动（散件），机械归因持有者，无主且宽限耗尽时以 major 告警浮出（同指纹按 24 小时滚动静默窗节奏，见「宽限与静默窗告警」）——散件滞留由分钟级机械巡检检出，而非 LLM 复盘车道的偶然检出。

## 规则

### 周期只读盘点

- daemon 主循环 60s 节拍对主树 tracked 未提交改动做只读盘点（`git status --porcelain`，排除 untracked，口径对齐既有 tracked-only 脏判定）；主树干净时零产出、零告警、零状态残留。纯 untracked 散件不在本能力覆盖内（构建产物类 untracked 噪音因此天然免疫）。
- 盘点在 worktree_manager 主树锁上以非阻塞方式参与互斥：锁被占用（merge-back 的 stash→merge→pop 写临界区进行中）即放弃本轮，不留痕为异常，下轮重试；绝不与写临界区并发，也绝不阻塞调用方主循环。
- 盘点接线禁设「无在飞 run」空闲预检（见 [ADR-258](../../adr/ADR-258-stray-sweep-readonly-observer-attribution-single-source.md)）——加了预检就永远看不到在飞车道、全部按无主误升级；必须把在飞实现车道 run_ids 传入归因（PMEngine 包装方法供参，盘点器按 WorktreeManager 句柄身份缓存复用，注册表进程内延续）。

### 指纹滞留计时（mtime 免疫）

- 滞留计时基于内容指纹的连续在场（见 [ADR-257](../../adr/ADR-257-maintree-staleness-content-fingerprint-no-mtime.md)）：指纹 = 改动路径排序集 + `git diff HEAD` 内容哈希（对 HEAD 求、含暂存+未暂存——纯 `git diff` 对纯暂存态散件为空、哈希退化为空串故不用；路径集与哈希 NUL 分隔防拼接歧义）。禁用 mtime 等可被外部 git 操作重写的时间戳作计时依据。
- 指纹不变沿用原 first_seen 继续计时（autostash pop 批量重写 mtime 不归零）；内容再被编辑即换新指纹，旧条目清除、新条目自当轮重新起算；改动消失（已被提交/stash/还原）即清除计时状态复位，不告警不残留。

### 占用者机械归因

- 复用合回 WIP 协调的既有机械归因器（`identify_wip_occupant` / `WipOccupantInfo`，见 [ADR-258](../../adr/ADR-258-stray-sweep-readonly-observer-attribution-single-source.md)），禁重造求交逻辑：改动文件集先与在飞实现车道 worktree 分支相对主树 HEAD 的改动集求交，车道归因零命中后归因器追加只读活交互会话探测——归因源全集、相关性门与 fail-open 规则见 [maintree-wip-attribution](maintree-wip-attribution.md)。
- 归因三分支：在飞车道命中 → status=holder 不计时不告警；活交互会话归因命中 → 受 `admin.maintree_session_attribution_action` 采信，缺省 info 降级 status=session-attributed 留痕（不计时、不派 major、不触发 admin 代查——计时条目连同升级标记整体出册，keep 则视同零命中）；真零命中 → 无主，自该指纹在注册表内建档时刻起算宽限（归因命中轮清计时后、消失轮重新建档的，起算点为重建档时刻，见「复发识别与根治指引」的归因转换再升级子形态）。
- 归因盲区随证据留痕：探测判据覆盖不到的主树直改形态仍零命中，一律按无主走宽限升级，升级仅为告警、误判影响有界，禁为覆盖盲区引入主树写探测。已知结构性盲区形态包括 dsh web 会话直改（活跃交互会话，但其每消息一次性 `claude -p` 执行形态使两探测源判据在告警时点确定性不满足，见 [maintree-wip-attribution](maintree-wip-attribution.md)）、非活跃会话遗留与主树内构建产物。
- 持有者命中期间持续 defer 不告警（与合回 WIP 协调的事件驱动等待同语义），在飞车道长期不终态不构成升级条件。

### 会话归因留痕状态收敛

- 「tracked WIP 归因到主树活交互会话」的 info 留痕按状态变化驱动：同一文件集（路径排序）且同一占用者会话仅在首次出现时落全量行；任一文件增删或占用者会话标识变更视为状态变化、落一条新留痕；状态未变的盘点轮次不落逐轮日志。
- 稳定期小时聚合：自上次留痕满 60 分钟落 1 条聚合行，含重复计数（「近 1h 重复归因 N 次，归因未变: <文件集>」），随后计数与窗口起点重置；留痕级别维持 info。
- 归因解除闭环：归因解除（文件消失、占用者清空、归因迁至在飞车道等迁移；宽限升级处置接管必先经归因消失轮）时补一条解除行；解除判定单点挂在归因分支之前，不依赖归因分支本轮被执行；解除后再归因按首次落全量行。
- 去重状态（上次归因键＝文件集+占用者会话标识、抑制轮计数、上次留痕时间戳）为进程内内存态：不持久化，daemon 重启后首轮按首次落行（允许一条重复）；不新增 AdminStore signal_type、不进人工队列。

### 宽限与静默窗告警

- 宽限配置 `admin.maintree_stray_wip_grace_minutes`，缺省 30，语义对齐 `admin.mergeback_wip_orphan_grace_minutes`；`0` 合法＝耗尽即升级（同指纹 24h 静默窗兜住刷屏）；解析失败/负值/NaN/inf/超一天上限一律回退缺省——配置事故既不放大成无限期静默等待，也不变成关闭降噪的极端。
- 宽限耗尽发 `maintree_stray_wip_stale` major 告警（经 AdminStore），同指纹告警节奏由「一次性」改为 **24 小时滚动静默窗**（evo-persist-stray-tracked-registry 1.2，2026-11-27 起）：候选轮查 `alert_history` 静默窗台账（随 tracked 注册表落盘 `.fenix/stray_tracked_registry.json`，跨重启连续）——无记录→发告警并记台账；距上次告警不足 24h→抑制（MUST NOT 写 AdminStore、MUST NOT 唤起 admin run，仅 suppressed_count 累计与 60 分钟聚合 info 日志，sweep 返回 status 维持 orphan-timed）；满 24h→正常重告，evidence 携带「静默窗抑制轮数=N」（与复发处置轮数分列），随后刷新台账。指纹演进按常规宽限正常告警。escalated_at 仍随计时条目写入并持久化（审计兼容）但不再是告警门槛。取代「一次性」的动因：两窗 7 轮 administrator 处置 run 空烧实证一次性门槛在人工散件长滞留场景被重启击穿（重启重置宽限后每宽限一条、37/35 分钟周期逐轮重发），「永不重告」又会让滞留散件彻底失察；24h 滚动窗把复发上界收敛为每指纹每 24 小时至多一条。
- 告警 evidence 附文件清单、first_seen、归因证据、盲区注记与零触碰注记；落库记录自带 `choices` 快照（缺键时消费端回退裁决注册表，现含 commit_stray_wip 提交与 untrack_stray_wip 根治两选项）。

### 复发识别与根治指引

- 告警发射时以 AdminStore 既有 `maintree_stray_wip_stale` SIGNAL 记录为台账检索同文件历史处置轮数：逐条解析 evidence「文件清单(N):」段（与执行器共用同一清单解析单源，防 manifest 形态漂移后双处解析失配）与本次文件清单求交，非空即记一轮；不另建台账文件。检索失败（store 不可读/解析链不可用）按 0 轮处理——退化为「首次处置」语义，不阻断告警发射（复发检索是增强信息，不是告警门槛）。
- 历史 ≥1 轮即复发型告警：evidence 追加复发注记（「已 N 度处置」计数与根治指引——执行裁决选项 `untrack_stray_wip` 或等效操作、或在处置记录挂显式跟踪项，MUST NOT 再以仅提交收尾），`recommended_action` 同步换根治优先口径。计数随告警下发，使「同文件第 2 度处置起必须根治」的义务在处置时点可判定（处置契约见 [admin-choices-contract](../admin-ops/admin-choices-contract.md)），不依赖处置方自行考古历史记录。
- 复发计数按「与历史告警文件清单求交非空」记轮，对跨日持续推进的同一活跃工作流（如 dsh web 会话逐日直改主树产生新 WIP 波）会稳定累积轮数、反复升级为复发型并要求根治；而根治选项 `untrack_stray_wip`（git rm --cached 出库 + ignore 吸收）面向生成物类散件，对源码/文档清单执行属仓库损伤。归属会话仍活跃的前提下，此类形态的升级为误报噪音——处置终态零触碰 resolved、清单内文件在 choice 执行时已不在当刻工作区改动中（归属者事后自行提交自愈），升级链只消耗 admin run 处置预算；归属会话已退场的同型升级是退场遗留形态，处置正解不同（见「活跃盲区与退场遗留判别」）。
- 复发噪音另有「归因出现→消失」转换再升级子形态：会话归因命中轮把该指纹的计时条目整体出册（宽限清零）；归因消失轮（典型如交互会话退场）走无主分支时注册表已无该指纹条目、以当轮时刻重新建档重起算宽限。历史上同指纹一次性去重以随条目存续的升级标记为准、对该路径不设防（同一 daemon boot 内同指纹可再度升级，活跃 dsh 工作流期间交互会话每开合一次即走完一轮「清计时→重起算→再升级」）；自 evo-persist-stray-tracked-registry（2026-11-27）起告警门槛改由独立分账的 alert_history 静默窗台账承载——pop 计时条目与复位不清台账，归因瞬时 pop 后同指纹重登记仍在 24h 窗内不重告，该转换再升级形态的告警频率由此封顶为每指纹每 24 小时至多一条（宽限重起算仍会推迟满窗后的重告时点）。
- 转换再升级形态按归属会话存续与否分型处置：会话仍活跃的走既有盲区噪音同型终态——处置方核验强归属实锤（源码 diff 注释自述用户需求、归属者自投递收件箱文件点名全部清单文件并附全量自检）后零触碰、显式跟踪项收口，散件由归属者自行提交自愈；会话已退场的走「退场遗留处置正解」分支，零触碰不再适用。
- `commit_stray_wip` 的清单约束（清单 ∩ 当刻 status、拒清单外路径）防越界、不防断链：散件盘点口径 tracked-only，清单内 tracked 文件 import 的 untracked 新组件永不在清单内——对含 untracked 依赖的改动集执行本选项必产生 HEAD 断链提交（verify 链与新 worktree 播种当即损坏）。执行本选项前由处置方核验清单内文件的 import 链闭合是必要前置；清单约束守卫不承担该核验。
- 首发型（0 轮）`recommended_action` 维持提交建议口径（带出 `commit_stray_wip`），与 admin_monitor `SIGNAL_RECOMMENDATION` 同文同步（防双处漂移）；复发型根治口径仅随告警记录 inline 下发。
- 告警经 admin_monitor 三表登记（SIGNAL_SEVERITY + SIGNAL_RECOMMENDATION + STORED_SIGNAL_TYPES）接入自动唤起 Administrator；落盘记录 evidence 以「项目名=」开头供摄取项目名解析收录（本告警无 spec 归属）。漏 STORED_SIGNAL_TYPES 则记录落 store 后无人摄取、升级出口落空。

### 活跃盲区与退场遗留判别

- 盲区噪音形态（零触碰正解）的成立前提是归属会话仍活跃、事后自愈。daemon 日志出现 worktree_manager 的「主树散件 WIP 会话归因解除」行、随后该指纹按无主重建档再走宽限升级，即标志归属会话已退场且未提交——自愈不会来，零触碰只会让散件无限滞留。
- 归因解除日志行是判别「活跃盲区」与「退场遗留」的关键锚点；升级告警 evidence 只携带当刻归因结论、不带历史命中轨迹，处置方 MUST 主动对账 daemon 日志取归因时间线，不能只按 evidence 的「无主」字面处置。
- mtime 同纳秒批量重写是 autostash pop 批量重写特征（对账「Stash popped after merge」日志行秒级吻合即实锤：pop 先写文件、数十毫秒后落日志），不构成「刚编辑过＝会话还活跃」的证据；内容指纹计时不受其影响（ADR-257 口径）。

### 退场遗留处置正解

- 退场遗留散件同时满足 (a) diff 内容完整自洽（注释自述动因、与既有 API 与键位兼容）且 (b) 正在挡在飞车道（WIP overlap precheck 反复 blocked、批保留待合回）时，处置裁决选项 `commit_stray_wip` 是 sanctioned 口径，含首发型（evidence 无复发注记）；复发注记不改变该形态的正解。
- 执行前置实测两项：import 链闭合（清单内 tracked 文件 import 的 untracked 组件一并入库，清单约束守卫不承担该核验，见「复发识别与根治指引」）与 hunk 文本重叠预检（与被挡分支同文件 hunk 确认零文本重叠再放行）。
- `untrack_stray_wip` 对源码/文档清单仍属仓库损伤，退场遗留形态不适用。
- 入库生效：散件盘点对已提交内容自动复位，被挡批下一轮合回自动放行。

### 零触碰与能力边界

- 盘点与升级链路全只读：MUST NOT 对主树执行 stash、stash pop、checkout、clean、reset 或任何改变工作区/索引内容的操作；一次盘点/告警前后 `git status --porcelain` 输出逐字节一致。框架仅报告：主树处置由处置程序显式发起，标准化提交与根治动作以裁决选项 `commit_stray_wip`/`untrack_stray_wip` 挂在裁决执行链（受清单约束与 signal_type 绑定守卫约束，见 [adjudication-actions](../admin-ops/adjudication-actions.md)），不在盘点链路内自动触发。untrack 根治落地后同路径改动由 .gitignore 自然吸收、不再进入 tracked 散件盘点口径（检测面零改动下自然止损）。
- ~~first_seen 与告警去重注册表为 daemon 进程内存态，重启即重置宽限，不引入持久化状态文件~~ **已被推翻**（evo-persist-stray-tracked-registry，2026-11-27）：tracked 注册表与静默窗台账落盘 `.fenix/stray_tracked_registry.json` 两分区（`tracked` 计时 + `alert_history` 台账），重启后宽限与静默窗跨重启连续。推翻依据：两窗 14 次处置 run 约 11.8 美元空烧、重启后 4/4 命中 69-71 秒重登记 first_seen——「损失仅时效」假设不成立（时钟存续介质与恢复语义见 [stray-escalation-clock-persistence](stray-escalation-clock-persistence.md)）。归因留痕/抑制日志等纯日志去重状态仍为进程内内存态（仅影响日志频率）。
- 本能力为独立旁路观察者，覆盖合回闸门看不见的散件形态（autostash 先行腾空主树使 WIP overlap 占用识别全程不触发，见 [mergeback-wip-active-coordination](mergeback-wip-active-coordination.md)）；不改动 autostash 路径、reclaim「脏不抢」语义与 WIP overlap 闸门任何现行行为，也不消费合回协调的台账与事件。

## 关键行为

- 单轮盘点流程：非阻塞取主树锁（忙则弃轮返回）→ `git status --porcelain` 取 tracked 改动（空集即 status=clean 零产出）→ 构造指纹并与注册表比对（新增档记 first_seen / 同指纹沿用 / 消失清除）→ 传入飞实现车道 run_ids 归因三分流（车道命中不计时 / 会话归因默认 info 留痕 / 无主按宽限计时）→ 无主且在场超宽限时查 alert_history 静默窗台账：无记录或满 24h → 写 AdminStore 告警（记录附 choices 快照）并记台账；窗内 → 抑制仅累计计数。盘点收尾原子落盘 tracked 注册表与静默窗台账（含本轮放弃路径）。

## 溯源

- 2026-10-08 evo-add-maintree-stray-wip-sweep（spec/archive/2026-10-08-evo-add-maintree-stray-wip-sweep） — 新建本页：主树 tracked 散件 WIP 周期只读盘点（60s 节拍、主树锁非阻塞互斥、tracked-only 口径）、内容指纹滞留计时（mtime 免疫）、复用 `identify_wip_occupant` 机械归因、宽限耗尽一次性 `maintree_stray_wip_stale` major 告警（admin_monitor 三表登记接入唤起）、全链零触碰仅报告。
- 2026-10-09 evo-add-maintree-interactive-session-attribution（spec/archive/2026-10-09-evo-add-maintree-interactive-session-attribution） — 修改本页：占用归因由二分支扩为三分支——车道归因零命中后归因器追加主树活交互会话只读探测，会话归因散件缺省降级 status=session-attributed info 留痕（不派 major 不触发代查），`admin.maintree_session_attribution_action=keep` 回退现状无主宽限升级；归因源与采信规则收敛至 maintree-wip-attribution 页。
- 2026-10-26 evo-add-commit-stray-wip-choice（spec/archive/2026-10-26-evo-add-commit-stray-wip-choice） — 修改本页：宽限升级告警落库记录自带 choices 快照，recommended_action 带出裁决选项 commit_stray_wip 并与 SIGNAL_RECOMMENDATION 同文同步；盘点与升级链路零触碰边界不变（提交动作在裁决执行链、不自动触发）
- 2026-10-27 evo-recurring-stray-remediation（spec/archive/2026-10-27-evo-recurring-stray-remediation） — 修改本页：新增复发识别段——同文件历史处置轮数以 AdminStore 既有 SIGNAL 记录为台账检索（清单段解析单源、失败按 0 轮不阻断发射），复发型告警 evidence 带「已 N 度处置」计数与根治指引、recommended_action 换根治优先口径（untrack_stray_wip），检测与触发逻辑本身不动；choices 快照与零触碰条款补记 untrack 选项
- 2026-10-30 evo-maintree-stray-attribution-log-dedup（spec/archive/2026-10-30-evo-maintree-stray-attribution-log-dedup） — 修改本页：会话归因 info 留痕由逐轮重写收敛为状态变化驱动（首现/变化落全量行、稳定期 60 分钟聚合行带重复计数、归因解除补解除行闭环），去重状态进程内内存态不持久化（动因实测：归因结论稳定时每轮重写同文案，5 天积累 5267 条、字节占比 57.9%）
- 2026-11-16 dsh-session-gap-in-maintree-wip-attribution（spec/knowledge/_inbox/done/dsh-session-gap-in-maintree-wip-attribution.md） — 补记归因盲区已知形态（dsh web 会话直改，结构性零命中）与复发计数放大噪音边界：跨日活跃工作流稳定累积复发轮数，根治选项 untrack_stray_wip 对源码/文档清单属仓库损伤、缺第三处置出口，升级全程误报噪音
- 2026-11-16 maintree-stray-sweep-refire-noise（spec/knowledge/_inbox/done/2026-11-16-maintree-stray-sweep-refire-noise.md） — 补记复发噪音「归因出现→消失」转换再升级子形态与同指纹一次性去重不设防点（归因命中轮清计时并销毁升级标记、消失轮重建档重起算宽限，同 daemon boot 内可再升级）；补记 commit_stray_wip 清单外断链反证（tracked 清单提交对含 untracked 依赖改动集必产生 HEAD 断链提交、处置前核验 import 链为必要前置）与强归属实锤零触碰处置形态；无主流形宽限起算点表述按建档/重建档口径改写
- 2026-11-27 evo-persist-stray-tracked-registry（spec/changes/evo-persist-stray-tracked-registry） — 修改本页：推翻「注册表内存态/损失仅时效/一次性告警」三项表述（两窗 14 次处置 run 约 11.8 美元空烧、重启 4/4 命中 69-71 秒重登记实证）——tracked 注册表落盘两分区文件、告警节奏改为同指纹 24h 滚动静默窗（alert_history 台账为门槛单源、escalated_at 降为审计、台账与计时条目分账封顶转换再升级形态、抑制轮 evidence 分列下发）；「归因出现→消失」转换再升级噪音与零触碰/能力边界条款同步改写
- 2026-11-27 maintree-stray-wip-attribution-release-exit-commit-over-zero-touch（spec/knowledge/_inbox/done/maintree-stray-wip-attribution-release-exit-commit-over-zero-touch.md） — 折叠 11-26 升级实例（指纹 c74e6c9db0f75832，admin run 1795735580 处置）：盲区噪音零触碰正解补「归属会话仍活跃」前提；新增「活跃盲区与退场遗留判别」段（归因解除日志行+无主重建档升级=退场遗留锚点、evidence 无历史轨迹→处置方对账 daemon 日志义务、mtime 同纳秒批量=autostash pop 特征判读）与「退场遗留处置正解」段（diff 自洽+挡车道双判据成立时 commit_stray_wip sanctioned 含首发型、import 链闭合与 hunk 零重叠双预检前置）；「升级全程误报噪音/处置零触碰同型」绝对化表述按会话存续收窄
