# merge-back-precheck 能力增量（add-pipeline-throughput-governance）

> merge 前置预检契约：merge 发起前对「主树 WIP 脏文件集 ∩ 分支触碰文件集」求交，非空即升级人工而非尝试 merge 失败回滚；与既有 overlap-gate 治理的关系与逃生门固化。

## ADDED Requirements

### Requirement: merge 前置交集预检

merge-back 发起前 MUST 计算主树 WIP 脏文件集（`git status --porcelain` 解析的未提交文件集）与实现分支触碰文件集（`merge-base..branch` diff 文件集）的交集；交集非空时 MUST NOT 发起 merge，MUST 转为人工升级告警（复用既有人工告警通道，内容含交集文件清单与两侧来源说明），spec 保持可重试状态（不冻结、不销毁分支与产物）。人工清理主树 WIP（提交/暂存/手术式分拣）后重试，或显式配置豁免。实现 MUST 复用 `core/worktree_manager/mergeback.py` 的 `_wip_overlap_gate`/`_detect_wip_overlap` 既有判定（evo-merge-back-wip-overlap-gate 治理已合入代码；`spec/archive/` 无同名归档目录，`core/wip_checkpoint.py` 为锚点提交机制），MUST NOT 重复实现同语义判定。本能力对既有闸门缺省行为属有意变更：交集非空的缺省处置从 auto stash 收纳（`_wip_gate_policy` 缺省，依据「重叠 ≠ 冲突」）改为升级人工拦截，实现 MUST 记录该策略变更依据并保留 `worktree.mergeback_wip_overlap_policy` 读侧兼容（block 并入升级出口）。

#### Scenario: WIP 重叠时拦截升级

- **WHEN** 某 spec merge-back 发起前，主树存在未提交修改 `core/agent_runner/runner.py`，且实现分支的 diff 也触碰该文件
- **THEN** merge 不被发起，发出含该文件清单的人工升级告警，spec 保持 done 可重试状态，分支与产物完好

#### Scenario: 无交集正常 merge

- **WHEN** 主树 WIP 与分支触碰文件集无交集（或主树干净）
- **THEN** merge-back 按既有路径正常执行，预检零额外开销（除一次 status/diff 读取）

#### Scenario: 逃生门跳过预检

- **WHEN** 配置显式豁免预检（如 `merge_precheck_bypass: true`）且触发 merge-back
- **THEN** 预检被跳过、merge 直接发起，冲突时按既有失败路径处理（与未引入本能力前一致）
