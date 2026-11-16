# Design: admin-orphan-effect-generation-aware

## 现状与根因

core/admin_monitor.py `_orphan_group_effect_evidence`（≈L7602）对具体 spec 处置组走 STATE 单源判定：STATE entry 在场时仅当 `not frozen and status != blocked` 才判生效，frozen=True 直接 return False（:7640-7650）。2026-11-11 事故中该短路把「处置生效→新代际再冻结」误判为「处置未生效」，假告警直链烧掉 2 次 arbiter 调查。

框架已有的状态推进留痕（transition / transition_gate 成功行均落 INFO 日志、结构化 context 含 channel，state_machine `_finish_transition` :3423-3435）足以重构「处置后推进轨迹」，但被 STATE 短路挡在门外——修复以读侧证据解除短路，无需新写入面。

## 方案

三级判定替换单源短路：

1. 代际锚点：处置组完成时刻。处置记录无独立终态时间字段（admin_store append 仅 setdefault `created`，:854），以组内最新记录的 created 时刻为锚点（与既有 grace 门 ③ 的 max(created) 口径一致，:7478-7484）。
2. 推进轨迹核查：挂接点在 STATE `frozen=True` 判 False 分支内（STATE 已判「解冻推进」的 True 短路保持前置，不给已推进 spec 增加扫描成本）；在日志窗（fenixd.log + 轮转备份）检索该 spec 在锚点之后的合法推进轨迹成功行，任一命中即判「已生效、被新代际取代」。轨迹匹配契约（关键：MUST NOT 逐字复用既有解冻族匹配谓词）：
   - 前缀两族都认：`Transition: <spec> <from> → <to>`（普通合法迁移，如 testing→verified，channel=auto——pm_engine/verification/legacy.py:965-968）与 `Gate transition: <spec> <from> → <to>`（门禁迁移，如复位直通道 blocked→testing，channel=recovery——admin_monitor.py:9005-9012）。既有 `_ORPHAN_UNFREEZE_TRANSITION_RE`（:1071）锚定 blocked 且刻意排除 Gate 前缀、deliberate-channel 过滤（:1067，manual/recovery）排除 auto——事故的两条决定性轨迹行恰好各被其一排除，逐字复用会使本 SPEC 的核心场景（事故重放）仍不命中。轨迹核查仅复用其读面（尾部限量 / 轮转候选集 / mtime 剪枝，`_read_recent_unfreeze_transitions` 同款），匹配谓词按本契约独立定义。
   - 行形态仅认成功行（INFO `Transition:`/`Gate transition: <spec> <from> → <to>`）；Cannot/Invalid/Idempotent/Frozen-stripped 等非成功形态（state_machine :3377-3421）不构成轨迹（与既有家族同口径）。
   - from→to 须属合法迁移（VALID_TRANSITIONS / GATE_TRANSITIONS）；spec 名与本组 spec 精确锚定；行时间戳落在 [锚点, now]。
   - channel 不限（auto/manual/recovery 皆认）：frozen spec 的自动推进本就被冻结剥离拦截（state_machine :3415-3421），锚点后能出现合法前移必然先有解冻/复位动作发生，方向安全；且事故时序中复位行与终态记录的先后不定，锚后可考轨迹可能只剩 testing→verified（channel=auto）一条，排除 auto 会漏。
3. fail-closed 兜底：无轨迹或日志不可用 → 维持现行升级人工语义，行为零变化。

判「被新代际取代」时的消解簿记（防回环与告警面污染，proposal 自身把 handled=false 污染列为痛点）：

- 旧处置组转记已消解（附轨迹证据行引用），转记为终态留痕、不带 escalate=true（② 门语义不变）。
- 旧组关联 SIGNAL 记录 MUST `mark_signal_handled` 收口（⑦ 分支同款出口，admin_store.py:1128）——既消解 handled=false 告警面污染，也使孤儿扫描 ④ 门（`unhandled_signal_for` 按组 sig_type 查询，:7486-7488）此后自然跳过本组，回环抑制不依赖新增扫描豁免门。
- 新代际信号条目 MUST 使用独立于旧组 sig_type 的类型键（如 superseded_generation 形态，经 store 既有 append 通道落账）：若复用旧 sig_type，④ 门会以旧键命中新条目、每轮重扫描重转记，形成同键回环。条目为回链留痕（携带旧组 id 与轨迹证据行），开立即终态/handled 形态——MUST NOT 进入未处理人工告警面，MUST NOT 触发人工升级或仲裁调查；冻结态本身的关注由既有解冻调度/监视机制负责。

## 取舍

- 不在 STATE 写入侧新增水位线字段（避免状态面 schema 变更与迁移成本），日志轨迹为读侧证据。
- 日志轮转窗口覆盖不到的更旧处置组：维持 fail-closed，不豁免。
- 不改 arbiter 回扫候选筛选：重复仲裁的上游抑制由 add-arbiter-blacklist-disposition 的防抖与本 spec 的假告警消解共同收敛，两者互补。
- 成本边界：轨迹核查只把日志扫描扩展到具体 spec 组的 frozen 判 False 分支（非每轮全量、已推进 spec 不入此分支），复用尾部限量读与 mtime 剪枝，最坏成本与既有 global 组日志家族扫描同量级（逐文件 ≤256KB × 轮转候选集）。
