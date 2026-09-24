# Design: deliverable-declaration-drift-align

## D1: 漂移判定（对齐孤儿预分类数据通道）

core/deliverables.py 已有孤儿判定数据通道（deliverable-dispute-orphan-preclassify，deliverables.py:1397 起）：
- `git log --all -- <path>` 历史命中检测（_git_path_history_hit，返回 {hit, commits}）
- 历史零命中 → 孤儿判定；历史命中 → 现行走人工（漂移特征）

本 SPEC 在「历史命中」分支前插入漂移对齐判定：

```python
def _locate_drift_target(
    project_root: str, declared_path: str, branch: str, merge_base: str
) -> list:
    """全仓定位拆包后候选落点。
    规则（确定性，无「同名字符串」之外的语义推断）：
    1. 取旧文件 basename 去 .py 作为**包目录名**（worktree_manager.py →
       worktree_manager/、pm_engine/dispatch.py → pm_engine/dispatch/）；
    2. 候选 = 该包目录内、且落在本次实现分支改动集合
       （`git diff --name-only --diff-filter=AM <merge-base>..<branch>`，
       既有用法见 core/worktree_manager/mergeback.py:757）内的 .py 文件——
       「本 SPEC 的改动落在哪个模块」只能由分支改动集合判定，包内文件按名字
       无法分辨（core/pm_engine/dispatch/ 实测 7 个模块）；
    3. MUST NOT 用 rglob 全仓同名文件兜底（同名冲突会伪造唯一性）。
    Returns: 候选列表（长度 1 = 可机械对齐；0 或 >1 = fail-open 回人工）
    """
```

scoring：候选先按「分支改动集合 ∩ 包目录内 .py」取交集；交集唯一（1 个）且该路径在实现分支 HEAD 真实存在（`file_exists_on_branch`，对齐 add-declaration-relocation-protocol 凭据三要素之 2——防「改声明 ≠ 交付物落地」）方判可对齐；交集零个或多个 → fail-open 回人工。

**复用既有原语（MUST NOT 另起一套）**：`add-declaration-relocation-protocol` 已落地（main HEAD 已含）同族能力，本通道 MUST 复用而非重写——
- 陈日信号：`is_stale_declaration`（core/deliverables.py:877，kind == modify 且主树 HEAD 无该路径）；
- 基线 basename 定位：`match_basename_in_tree`（core/deliverables.py:1166）；
- 生效声明读取：`resolve_effective_declaration` / `Dispatcher._effective_declaration`（adjudication.py:23）；
- 改写与凭据：`relocate_declared_path` / `register_relocation_credential`（core/deliverables.py:919/936）。

**与 `_preclassify_stale` 的关系（互斥、单轮单通道）**：`_preclassify_stale`（adjudication.py:714）只挂在 `_adjudicate_deliverable_missing` 链上，而实现 run 提出 deliverable-dispute 异议时走 `queue.py:897` 的争议分支、**不进入** `_adjudicate_deliverable_missing`（queue.py:894-980）——即异议形态下 `_preclassify_stale` 不可达，本通道正是补这一段。同一轮同一 spec MUST NOT 由两条通道各改写一次声明：本通道先行，失败（零/多候选）即回退既有人工通道，MUST NOT 再触发重定位改写。

## D2: 机械对齐与审计

对齐执行（**改写目标 = 生效声明所在位置**，与 D1 同源）：
1. 经 `_effective_declaration`（adjudication.py:23）取生效声明与 `spec_dir`；`spec_dir` 为 None（来源为分支版本，无落盘位置）→ **不执行改写**，转「凭据登记」分支（`register_relocation_credential`，core/deliverables.py:936）。MUST NOT 直写主树 `spec/changes/<spec>/tasks.md`——改写与守卫读取错位正是 add-declaration-relocation-protocol 立 SPEC 的根因（其 proposal.md「Why」节）。
2. 生效声明仍含该条目 → 复用 `relocate_declared_path(effective_spec_dir, old, new)`（core/deliverables.py:919，逐行精确替换、kind 保持、同名去重，MUST NOT 另写改写函数）
3. 改写后立即提交生效声明所在位置（复用 `_commit_softened_declaration`，adjudication.py:289；合入偏差会触发 merge 死锁，见其 docstring 引用的 2026-09-15 事故）
4. 写 audit：`{"type": "relocation", "spec": ..., "old_path": ..., "new_path": ..., "source": "mechanical-branch-diff", "verdicts": [{"element": <声明路径>, "verdict": "drift-aligned", "actual_path": <新落点>, "reasoning": "..."}]}`（`verdict=drift-aligned` 与 `type=relocation` 双写，使 D3 收缩防护的 `_has_relocation_credential` 能命中；MUST NOT 简化 `before/after` 为单调 diff）
5. 解除 blocked：清 error、置回 implementing（若实现 run 仍可重入）或 ready 重排

fail-open 准则（高度保守）：任何一步异常（生效声明读取失败、找不到声明行、候选不唯一/不唯一可达、写回/提交失败）→ 终止机械对齐，走既有人工裁决通道。

## D3: 派发前同源草案收敛检查

core/pm_engine/engine.py `_on_spec_ready`（派发 implementer 前）：
1. 收集 spec/changes/ 下所有目录的 SUPERSEDED.md
2. **解析以显式点名为唯一判据**：被取代目录名以 inline code（反引号）或路径形态出现在该页正文中（现行实例 spec/changes/evo-merge-back-wip-overlap-gate/SUPERSEDED.md 的「**生效实现落点**：``spec/changes/evo-merge-back-wip-overlap-gate-575976/``」即此形态）。MUST NOT 依赖 `.spec.yaml` 的 capability 字段——实测全仓 `.spec.yaml` 无 capability 键（`grep -rn "^capability" spec/changes/*/.spec.yaml` 零命中），且本 spec 与 `-575976` 各只有一份 capability 目录（worktree / merge-back），文档自述的「capability + name 归一」不可实现。
3. 名字归一兜底：本 spec 目录名去掉数字后缀后与他目录名相等（`_NUM_SUFFIX_RE`，core/evolution.py:1498；`-_575976` / `-<6位 id>` 均由此产生，见 evolution.py:1040-1042）。归一命中的**两侧含义不同**：
   - 对方目录含 SUPERSEDED.md（如本目录是收敛源、对方是生效落点）→ **不拦截本方**；
   - 本方目录含 SUPERSEDED.md → 拦截本方（见第 4 条）。
4. **拦截面只限「本 spec 目录自身含 SUPERSEDED.md」**——该标记由收敛动作主动写入（先例：commit 023346ff / 42af955e），语义明确「本目录不再作为独立实现入口」。MUST NOT 仅因「平级存在同名草案」就 blocked：`-575976` 是被 `SUPERSEDED.md` 点名的**生效落点**，按名字归一会与收敛源互为命中，误拦会把生效草案永久冻住。命中 → 置 blocked（error=同源草案收敛义务未满足: <SUPERSEDED.md 相对路径>）。
   - 实现位置以 `_on_spec_ready` 为主（engine.py:529）；「只针对 implementer/fast-track 派发条目」的口径须同样落在 `_process_queue` 候选筛选（queue.py:61 `_enqueue` / queue.py:148 `_process_queue`）——`_on_spec_ready` 只覆盖 4 条主入口，定时重派与恢复车道直入队列的条目（该文件 :604 注释点名的旁路）不经过它。
5. 收敛完成的信号：被取代目录被删除或 SUPERSEDED.md 被移除（本目录 SUPERSEDED.md 删除即解除拦截；对侧生效落点自始不受拦截）。

## D4: 测试策略

tests/test_deliverable_drift_align.py：
- 漂移判定：mock git 历史命中 + 分支改动集合，覆盖唯一候选/多候选/零候选（fail-open）、以及 `core/worktree_manager.py` / `core/pm_engine/dispatch.py` 真实拆包形态（包内多文件、分支改动集合唯一命中）为唯一候选的取证
- 对齐执行：构造临时 spec 目录（tasks.md 声明段 yaml），断言改写 + audit 落盘 + blocked 解除；并断言 `spec_dir=None`（分支来源）时走凭据登记、不改写主树
- 同源检查：两草案目录 + SUPERSEDED.md，断言**含 SUPERSEDED.md 一侧被拦截、对侧生效落点正常派发**，及解收敛（删除 SUPERSEDED.md）后恢复派发