# 已合并 fenix 分支自动回收（分支 GC）

<!-- knowledge: capability=merged-branch-gc rev=1
     sources=spec/archive/2026-10-31-add-merged-branch-gc -->

worktree 陈旧清扫内的已合并分支回收环节：回收满足全部安全条件的实现/验证分支 ref，使每轮时间戳新分支的累积有界化。

## 规则

### 触发与宿主

- 分支 GC 挂在 worktree 陈旧清扫（stale_sweep）内、在既有清扫锁内执行，不新增调度面；清扫由 daemon 启动路径触发（无周期调度），故 GC 形态为「每次 daemon 启动回收一轮」，长驻运行期间新增的已合并分支留待下次启动回收。
- `worktree.branch_gc.enabled: false` 时完全跳过（零扫描零删除）；关闭状态与零删除轮均静默，不产日志噪音。

### 四条件判定（缺一不删）

- 扫描范围为命中实现/验证分支前缀家族的分支（复用 `worktree.implement_branch_prefix`，默认 `fenix/`），同时满足以下全部条件才删：
  1. 已完全并入基线分支（`--merged` 口径；基线走 `resolve_base_branch`：origin/HEAD → main → master 回退，不硬编码 main）；
  2. 分支 tip 提交时间早于宽限期（`worktree.branch_gc.retention_days`，默认 7 天）——保留 deliverables 读侧 D1 兜底（`git show <branch>:tasks.md`）与验证 diff 参照的读取窗口；
  3. 未被任何已登记 worktree checkout（如 fast-track 保留复用场景）；
  4. 所属 spec 在 STATE.md 中不存在（已归档/已删除）或处于非活跃状态。
- 删除动作只允许 `git branch -d`（拒绝未合并分支的删除语义），MUST NOT 使用 `-D`：扫描与删除之间的并发变化由 `-d` 拒绝兜底，最坏结果是漏删（下轮重扫），不存在丢内容路径；已合并分支的提交仍从基线可达、可按 sha 重建。见 [ADR-307](../../adr/ADR-307-branch-gc-d-only-safety-boundary.md)。
- 单分支删除失败不中断整轮清扫，失败分支留待下轮（与既有清扫环节同口径）。

### 活跃豁免与竞争避让

- spec 活跃豁免 = 两守卫并集：`_branch_protected_by_state` 在飞引用保护（单一来源复用、不复制常量）∪ STATE.md 显式活跃状态集判定（implementing / implemented / testing / reviewing / ready(+_recovery_resume) / blocked(+frozen+_frozen_hold)）。后者补齐前者未覆盖的 reviewing 等活跃状态，豁免优先于合并与 tip 新旧判定（宁漏勿误）。STATE.md 新增活跃状态时 MUST 同步本状态集枚举。
- spec 名从分支名解析，规则与 `_spec_from_branch` 现有口径一致（去前缀、末段纯数字时间戳、verify- 按验证分支语义剥离）；解析失败（含非 fenix 配置命名空间）的分支一律跳过不删。
- 被在册 recovery legacy 登记（`_legacy`，宽限期内同分支再登记含在内）引用的分支 MUST 跳过——删除留给 legacy 兜底回收链（`_reclaim_expired_legacy`）按其既定口径执行，避免 GC 与之竞争同一分支致「续做」降级为从零重派。

### 能力边界

- 未合并分支不进自动 GC：git cherry 补丁等价检测慢且「补丁等价≠内容已采纳」；未合并分支数量仅进日志计数留人工甄别。
- 不建备份 ref 机制：`-d` 口径下零内容损失，备份只是把 ref 膨胀换名字重演。
- 不改每轮时间戳新分支命名（并发正确性设计，与回收正交）；前缀家族之外的遗留分支不做处理，留人工。

### 配置与界面

- `worktree.branch_gc.enabled`（bool，默认 true——缺省即收敛，关闭是显式动作）；`retention_days`（int，默认 7，最小 1；0/负数/非整数按无效值回退默认 7，不抛异常、不中断清扫轮）。缺省值在配置模板带注释说明。
- 配置键与 Dashboard 设置页同步提供分支 GC 面板（开关 + 宽限期天数输入），保存走既有配置写回通道（热更新覆盖生效），面板重开回显当前值。

### 可观测性

- 执行了删除的轮次 MUST 记日志：删除分支名清单、删除总数、分档跳过计数（未合并 / 宽限期内 / 活跃 spec / worktree 占用）。

## 关键行为

- 单轮 GC 流程：随清扫锁进入 → 扫描前缀家族分支并按 `--merged` 预筛（未合并分支只计数不删）→ 逐分支评估四条件与活跃/legacy/worktree 豁免 → 对通过者执行 `git branch -d` → 汇总删除清单与分档跳过计数落日志；零删除静默。

## 溯源

- 2026-10-31 add-merged-branch-gc（spec/archive/2026-10-31-add-merged-branch-gc） — 新建本页：stale_sweep 内已合并分支 GC（四条件判定、`-d` 语义硬边界、活跃豁免两守卫并集补齐 reviewing、legacy 登记避让、宽限期默认 7 天、worktree.branch_gc.* 配置与 Dashboard 面板、结构化运行日志）。
