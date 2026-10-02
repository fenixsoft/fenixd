<!-- knowledge: capability=merge-back-precheck rev=1 sources=spec/archive/2026-09-27-add-pipeline-throughput-governance -->

# merge-back 预检（WIP 交集升级拦截）

merge-back 发起前的交集预检：主树 WIP 与实现分支触碰文件重叠时不尝试「merge 失败再回滚」，而是拦截升级人工，避免整轮实现因合流受阻作废。

## 现行规则

- merge-back 发起前 MUST 计算主树 WIP 脏文件集（`git status --porcelain` 解析的未提交文件集）与实现分支触碰文件集（`merge-base..branch` diff 文件集）的交集；交集非空时 MUST NOT 发起 merge，MUST 转为人工升级告警（复用既有人工告警通道，内容含交集文件清单与两侧来源说明）。
- 拦截不惩罚 spec：spec 保持可重试状态（不冻结、不销毁分支与产物）；人工清理主树 WIP（提交/暂存/手术式分拣）后重试，或显式配置豁免。
- 复用既有判定：实现 MUST 复用 `core/worktree_manager/mergeback.py` 的 `_wip_overlap_gate`/`_detect_wip_overlap`，MUST NOT 重复实现同语义判定。
- 策略缺省与兼容：交集非空的缺省处置为升级拦截（escalate）；`worktree.mergeback_wip_overlap_policy` 读侧兼容——显式 `auto` 维持旧自动收纳语义，显式 `block` 并入升级出口；读取/解析异常回退 escalate（宁紧勿松）。
- 逃生门：`worktree.merge_precheck_bypass=true` 时跳过预检直接 merge，冲突按既有失败路径处理；逃生门读取异常一律 False（fail-open）。
- 无交集（或主树干净）时按既有路径正常 merge，预检零额外开销（除一次 status/diff 读取）。

## 溯源

- 2026-09-27 add-pipeline-throughput-governance（spec/archive/2026-09-27-add-pipeline-throughput-governance） — 新增 merge 前置交集预检：交集非空缺省处置从自动收纳改为升级人工拦截，保留 `mergeback_wip_overlap_policy` 读侧兼容（block 并入升级出口）与 `merge_precheck_bypass` 逃生门
