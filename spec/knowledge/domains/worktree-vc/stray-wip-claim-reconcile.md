# 主树散件升级告警指纹入库认领核销

<!-- knowledge: capability=stray-wip-claim-reconcile rev=1
     sources=spec/changes/evo-add-stray-wip-claim-reconcile -->

maintree_stray_wip_stale 升级告警的消费端闭环：人工以提交认领主树直改形态后，周期盘点机械探测「指纹文件集全部入库」并自动核销悬置告警条目——终结「人工已处置但告警永久挂账、复发升级逐度空转消耗 admin run 处置预算」的悬置面。

## 规则

### 探测范围与文件集来源

- 探测只挂 maintree_stray_wip_stale 族 kind=SIGNAL 且未核销（handled=False）的条目（白名单单族，照告警自动闭环先例 [ADR-043](../../adr/ADR-043-alert-auto-resolve-condition-whitelist.md)）；disposition 留痕记录无文件集且不属 SIGNAL 唤起面，不参与，其闭合走既有链上台账机制。
- 指纹文件集以条目结构化字段 `fingerprint_files` 为准（升级条目落库时写入，与 evidence「文件清单(N):」段同源）；无结构化字段的存量条目按 evidence 段回提取——提取单点 `admin_store.stray_claim_fingerprint_files`（复用段级解析 `parse_stray_wip_manifest`，禁另写路径正则双处解析）。两者皆不可得＝回提取失败，保守跳过（条目保留原状）。
- 探测只消费结构化字段或可回提取的 evidence 文本，不依赖自然语言全文理解。

### 认领判据（机械 git 事实，一问即答）

- 判据＝指纹文件集全部被条目基线（created）之后的提交覆盖（≥1 个提交、覆盖提交数不限，多波覆盖均可）且工作区该集合 clean。在本 sweeper project_root 内以只读 `git -C` 一问即答（`git log --name-only` + pathspec `:(literal)` 字面化防 glob 元字符误匹配清单外路径），不跨仓。
- 任一文件未被基线后提交覆盖（部分入库）或集合内仍有脏文件（含 untracked 出库散落形态）→ 条目逐位保留（handled 不变），升级节奏与人工队列可见性不变；防半处置假闭环由「全覆盖 ∧ 集合 clean」共同承担，与提交数无关。
- 人工以非提交形态处置（stash/手动删除）不命中：条目继续悬置走既有升级路径，行为等于无本能力，不构成回归。
- 探测全只读、零触碰（AdminStore 只读 + git 只读）；插桩 MUST 在盘点轮空集早退**之前**——人工提交完指纹集后恰是 tracked 空集形态，插桩在后则核销目标时点永不执行（早退不得吞掉本流判定，与白名单巡检同款红线）。

### 自动核销写回

- 命中即核销：handled=True、handled_by="auto-resolve-claim"、handled_at、resolve_note 回填最近覆盖提交 SHA（多波覆盖取最近覆盖提交）与转向话术「人工已以提交认领主树直改形态，请确认是否仍需建立 worktree 车道」。
- 写回单点 `AdminStore.auto_resolve_claim`：signal_type 全等白名单，只核销 kind=SIGNAL 且未 handled 的记录（人工/既有处理记录不可覆盖），只改 handled 族字段、不伪造人工处理记录；单次排他锁内读-改-写，无可核销条目零写回（mtime 不变）。
- 消费端核销与人工后续裁决分离：核销不自动建立 worktree 车道，只在 resolve_note 转向提示人工确认（入库 commit 是机械证据，与告警生命周期「只认机械证据」宪章一致）。
- 核销后旧条目出账：退出悬置面（人工队列与悬置视图按 handled=False 收纳），不再消耗该条目的处置预算；同文件此后新产生的散件波按既有盘点口径独立告警，与本能力无关。

### 核销署名与复发台账互斥

- 复发计数台账检索（`_prior_stray_rounds`）MUST 跳过 handled_by="auto-resolve-claim" 的记录：自动核销不是人工处置轮，计入会使下次同文件告警误带「已 N 度处置」复发根治口径（人工从未处置过该文件；untrack 根治对源码清单属仓库损伤）。

### 保守缺省

- 文件集回提取失败 / created 不可解析 / git log 不可用 / store 不可读 / 核销写回失败一律跳过、条目保留，不阻断本轮盘点：不核销的代价是继续悬置（现状），误核销的代价是吞掉真问题，保守侧正确。

## 关键行为

- 单轮探测流程：读 store 取未核销本族 SIGNAL 条目 → 逐条取文件集与基线时刻 → 一次 `git log --name-only` 取回全部候选文件触碰史 → 逐条判「集合 ∩ 脏集为空 ∧ 文件 ⊆ 基线后覆盖集」→ 命中组装 resolutions（最近覆盖提交 SHA + 转向话术）→ `auto_resolve_claim` 批量核销。插桩位置在 status 取回后、一切空集早退之前。

## 代码锚点

- 主实现：core/worktree_manager/stray_wip.py（`_claim_reconcile_locked` 认领探测、`_write_alert` 落库附 `fingerprint_files`、`_prior_stray_rounds` 署名互斥跳过）
- 核销写回与回提取单点：core/admin_store.py（`auto_resolve_claim` / `CLAIM_RESOLVE_BY` / `stray_claim_fingerprint_files`）
- 消费面：core/admin_monitor.py（escalated 未处理条目摄取豁免所在，核销后 handled=True 出账）
- 守卫测试：tests/test_stray_wip_claim_reconcile.py（核销/保守反例/插桩断言/署名互斥）、tests/test_maintree_stray_wip_sweep.py（盘点侧零回归）

## 溯源

- 2026-11-16 evo-add-stray-wip-claim-reconcile（spec/changes/evo-add-stray-wip-claim-reconcile） — 新建本页：升级条目落库附结构化指纹清单；周期盘点挂认领探测（空集早退前插桩、全覆盖+集合 clean 判据）；存量 evidence 回提取；核销署名 auto-resolve-claim 与复发台账互斥
