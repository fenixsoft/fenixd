# 修复批合回 WIP 阻断延迟合回

<!-- knowledge: capability=code-fix-wipgate-defer rev=1
     sources=spec/archive/2026-09-29-fix-codefix-wipgate-defer -->

自动修复车道批收尾合回被主树 WIP 重叠预检阻断时的处置语义：暂态阻断零预算消耗、批现场保留、主树清理后链边界自动合回核销。

## 规则

### 合回阻断分类
- 批收尾合回失败时 MUST 先读 `merge_info.wip_gate_blocked` 分派两条互斥路径：`True` 走延迟合回（defer）路径，进度 reason 恒为 `wip_gate_blocked`；`False`（真内容冲突或其他 git 失败）维持现场即弃路径——`record_failed_batch(reason="merge_back_conflict")` + `_safe_cleanup(success=False)` + `fail_count` 预算照常。
- 分类只读结构化标志，禁止解析错误文案；`getattr` 缺省 `False` 保证对无该属性的旧冲突对象容错。
- 两条路径的进度文案 MUST 可区分：「主树未提交改动挡住合回」与「合回冲突」。

### 延迟台账与现场保留
- defer 路径把批记入台账 `.fenix/code-review/fix-deferred.json`（原子写），条目八字段：`worktree`、`branch`、`tip_sha`、`item_ids`、`fixed_ids`、`defer_count`、`first_deferred_at`（UTC ISO8601）、`last_overlap`（交集文件清单）。同条目集幂等复用既有条目：刷新现场字段，`first_deferred_at`/`defer_count` 不因复写漂移。
- `fixed_ids` 是批产物行 `status=="fixed"` 的核销集合，核销只覆盖其中仍 `open` 的条目。`mark_resolved` 对命中 id 无条件置 resolved、无终态保护，核销方 MUST 先经 `read_items` 过滤，否则 defer 窗口内被人工置终态的条目（如 skipped/ignored）会被白洗成 resolved。
- defer 不删现场：worktree 目录与分支留在磁盘，`_active_worktrees` 保持在册（sweeper 扫孤儿跳过在册目录）；同时 MUST 经 worktree lifecycle 的 `release_spec_lock` 原语（只清锁与 lock_since，不动目录/分支/活动集）显式释放 `code-review-fix:code-fix` spec 锁。同键 `wm.create()` 命中锁即返回 None、批 worker 对 None 走 halt 终止链——只保留现场不放锁，defer 后下一批建树必败，整条车道在主树脏期间死锁。
- defer 条目的 `item_ids` MUST 并入选批排除集（`select_batch` 的 `exclude_ids` = `chain_skipped` ∪ 台账 item_ids 并集）：defer 条目在合回成功前始终 `open` 且不在失败档案，不排除会被下一边界 earliest-first 立即重选、重跑 agent。
- wip_gate_blocked 失败本身不污染主树与 worktree 状态（merge 未发起，升级拦截出口保证）；首次进入 defer 路径即发一条 info 级 admin 告警（`signal_type=code_fix_wip_gate_deferred`），正文含交集文件清单与「主树清理后链边界自动合回」提示。

### 自动重试合回
- 链在两个时机重试延迟批（对保留 worktree 直接重跑 `wm.merge_back`，不重跑 agent）：① 每批 worker 收尾后的链边界、选下一批之前；② 链收敛出口、`count_open_items==0` 早退之前。重试点均在 checkpoint 锁段内，批在飞时 checkpoint 按 `already_running` 早退，重试不与在飞批的建树/合回交叠。
- 重试结果四分派：成功 → 核销 `fixed_ids` 中仍 `open` 的条目 + `_safe_cleanup(success=True)` + 移出台账 + 进度 done 累加，文案「延迟批合回成功（核销 N 条）」；仍 `wip_gate_blocked` → 台账保留、`defer_count` 递增 1；失败且非 `wip_gate_blocked`（主树 WIP 已被提交后内容真冲突或其他 git 失败）→ 按真冲突同语义入失败档案（`reason="merge_back_conflict"`）+ 清理 + 移出台账；抛异常 → 记 warning 后继续，不炸链节拍。
- `defer_count` 与预算时间门只在实际尝试过 merge_back 时推进（纯等待不递增）；`first_deferred_at` 永不重置。

### 预算双门与降级告警
- 延迟批预算双门先到为准：`first_deferred_at` 起超过 90 分钟（模块常量 `DEFER_BUDGET_SECONDS`），或 `defer_count` 达 6 次（模块常量 `DEFER_RETRY_MAX`；首记即 1——批收尾那次被阻断的合回即第一次实际尝试）。两常量均非配置键，无 Dashboard 配置义务。
- 耗尽判定：条目按 `reason="wip_gate_blocked_expired"` 入 `fix-failed.json`（`fail_count` 正常递增）→ worktree 走失败收尾（success=False 遗产分支，目录由 sweeper 宽限期兜底回收）→ 移出台账 → 发一条 warning 级 admin 告警（`signal_type=code_fix_wip_gate_defer_expired`），含交集文件清单与「提交（git add/commit）或 stash（git stash push）主树改动」处置提示。
- 降级告警一次性语义按条目集指纹去重：指纹只用 `item_ids`，不混入 worktree/tip_sha 等逐次不同的字段；同条目集再次过期降级不重复告警。

### 换链与重启再认领
- 新链启动（`activation_id` 更替）扫台账再认领：worktree 目录仍存在且 `tip_sha` 可在分支解析 → 原样保留继续重试（`defer_count`/`first_deferred_at` 沿用不重置，链边界重试照常覆盖）；worktree 已不存或分支不可解析 → 移出台账 + 记 warning 日志，条目从未核销而天然仍在 open 池，可被后续链重新选批。
- 台账文件持久化，daemon 重启不丢延迟批；丢失回收只记日志，不发 admin 告警。

## 溯源

- 2026-09-29 2026-09-29-fix-codefix-wipgate-defer（spec/archive/2026-09-29-fix-codefix-wipgate-defer） — 新建本页：合回阻断二分类（暂态 defer 零预算 / 真冲突现场即弃不变）、fix-deferred.json 台账与现场保留+显式放锁、链边界与收敛出口双时机自动重试、90 分钟/6 次预算双门降级与一次性告警、换链与重启再认领。
