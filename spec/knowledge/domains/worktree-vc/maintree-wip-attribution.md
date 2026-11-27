# 主树 WIP 占用归因单源（在飞车道与活交互会话）

<!-- knowledge: capability=maintree-wip-attribution rev=3
     sources=spec/archive/2026-10-09-evo-add-maintree-interactive-session-attribution,spec/knowledge/_inbox/done/dsh-session-gap-in-maintree-wip-attribution.md,spec/knowledge/_inbox/done/maintree-stray-wip-attribution-release-exit-commit-over-zero-touch.md -->

identify_wip_occupant 是全框架「主树未提交改动归谁」的单一机械归因源：先按在飞车道分支求交，零命中再只读探测主树活交互会话；散件盘点、合回 WIP 协调与 code-fix 延迟合回告警共用同一归因输出。

## 规则

### 归因单源与顺序

- 主树 WIP 占用归因一律单源复用 `identify_wip_occupant` / `WipOccupantInfo`（见 [ADR-258](../../adr/ADR-258-stray-sweep-readonly-observer-attribution-single-source.md)），消费者禁复制探测逻辑；归因纯机械（worktree 注册表、git 查询、文件读），MUST NOT 引入 LLM 推导路径。
- 归因顺序固定：先在飞车道归因（impl-/code-fix- 前缀在飞 run 的 worktree 分支相对主树 HEAD 改动集与散件求交）；仅当车道归因零命中时才追加活交互会话探测，会话探测不得抢占既有车道归因结果。

### 活交互会话只读探测

- 主源（最近提交人启发）：项目配置 git 身份（user.name/user.email 任一配置）在 24h 窗口内有提交，且散件路径与其最近提交触碰集相交——身份、时间窗、路径交三判据同时满足；两侧身份都未配置即源缺失放弃。
- 辅源（transcript 活跃信号，主源零命中时兜底）：`~/.claude/projects/<主树路径 munge>` 下 mtime 在 30 分钟活跃窗内的交互会话 transcript，按活跃度新→旧至多查 5 份、每份只扫尾部 256KB，尾部出现散件路径提及即命中——活跃窗 + 工作范围交叠判据。
- 相关性门：任一探测源构成命中 MUST 含散件与会话的相关性信号（路径交或路径提及）；仅「存在活跃交互会话」MUST NOT 单独构成归因命中，否则真实滞留散件会被活跃会话吞掉（见 [ADR-263](../../adr/ADR-263-maintree-session-attribution-relevance-gate-single-key-rollback.md)）。
- 探测全程只读（git config/log、transcript 文件读），MUST NOT 为归因写入主树；零命中、源缺失、任何异常一律 fail-open 回「无主」，行为与无探测时逐位一致，不新增误报。

### 已知结构性盲区：dsh web 会话直改形态

- dsh web 会话（dsh web 端交互会话）的 agent 执行形态是每消息派生一次性 `claude -p`（stream-json）子进程、消息结束进程即退。该形态直改主树的活跃 WIP，到宽限 30 分钟耗尽、升级告警发射的探测时点必然处于「改动未入库、编辑进程已退」形态——近窗提交人启发要求改动已入库、transcript 活跃信号要求告警时点会话足迹在场，两源判据对其确定性不满足，归因恒零命中、按无主走宽限升级。这是结构性盲区，不是偶发抖动。
- 该形态的升级是否为噪音、零触碰是否为处置正解，以归属会话是否仍活跃为前提：会话活跃＝choice 执行时清单内文件已全部不在当刻工作区改动中（归属者事后自行提交、WIP 自愈），处置终态零触碰 resolved，升级链只消耗 admin run 处置预算；会话已退场且未提交（自愈不会来）＝退场遗留形态，零触碰只会让散件无限滞留，处置正解转裁决选项 `commit_stray_wip`——判别锚点（daemon 日志归因解除行）与处置判据见 [maintree-stray-wip-sweep](maintree-stray-wip-sweep.md)。

### 会话归因形态与消费者透明生效

- 会话归因是 `WipOccupantInfo` 的独立 occupant 形态（source=maintree-interactive-session，holders 带 kind=interactive-session 与会话线索）：命中时 evidence 标注会话线索，不再自认无主盲区。
- 会话归因 holders 无 run_ids、无 spec/分支，不构成可注册终态回调的在飞持有者——事件驱动重试自然缺席，由既有周期轮询兜底。
- 归因输出对全部消费者透明生效：散件盘点、合回协调与 code-fix defer 告警的 evidence 均携带同一会话归因文本（describe()），各消费者不复制探测。

### 采信回退全局单键

- `admin.maintree_session_attribution_action`（info|keep，缺省 info）是会话归因采信的唯一回退开关，盘点侧与 code-fix defer 侧共用同一读取器：info＝采信——盘点侧降级 status=session-attributed info 留痕（附会话线索与指纹；计时与复位同在飞车道命中分支，不累计宽限），不派 `maintree_stray_wip_stale` major、不触发 admin 代查，defer 侧记 owner_kind=holder 且宽限计时清零；keep＝两侧都把会话归因视同零命中，走既有无主宽限升级现状流（evidence 仍透传会话线索）。禁「盘点侧可回退、defer 侧无开关」的不对称。
- 降级留痕走盘点结构化返回值与既有日志通道，MUST NOT 新增 AdminStore signal_type（免 admin_monitor 三表登记缺口——漏登记则落 store 后无人摄取）。
- 配置非法值守卫回退 keep（保守方向：配置事故 MUST NOT 静默吞 major），info 只在显式合法值上生效。

## 溯源

- 2026-10-09 evo-add-maintree-interactive-session-attribution（spec/archive/2026-10-09-evo-add-maintree-interactive-session-attribution） — 新建本页：车道归因零命中后的主树活交互会话只读探测（最近提交人启发主源 + transcript 活跃信号辅源）、相关性信号门、fail-open 回无主、会话归因 occupant 形态、`admin.maintree_session_attribution_action` 全局单键对称回退（盘点降级 info + defer 采信同键约束）。
- 2026-11-16 dsh-session-gap-in-maintree-wip-attribution（spec/knowledge/_inbox/done/dsh-session-gap-in-maintree-wip-attribution.md） — 补记已知结构性盲区：dsh web 会话直改形态（每消息一次性 claude -p 执行形态使两探测源判据在告警时点确定性不满足，归因恒零命中按无主升级）；三度同型误报升级实证（11-10/11-11/11-13，处置零触碰 resolved、归属者事后自行提交自愈）随盲区留痕
- 2026-11-27 maintree-stray-wip-attribution-release-exit-commit-over-zero-touch（spec/knowledge/_inbox/done/maintree-stray-wip-attribution-release-exit-commit-over-zero-touch.md） — 修改本页：盲区段「升级全程误报噪音、处置一律零触碰」绝对化定性废除，改为按归属会话存续分型（活跃＝零触碰自愈；退场未提交＝退场遗留，处置正解转 commit_stray_wip）；判别锚点（归因解除日志行）与处置判据收敛至 maintree-stray-wip-sweep 页
