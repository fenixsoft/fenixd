## Context

2026-10-27 取证：主仓库累积 2157 条 `fenix/*` 分支（2041 条已并入 main，116 条未合并），
无任何回收机制。结构性根因有两个：

1. **每轮新分支命名**：`core/worktree_manager/lifecycle.py` 为规避 re-verification 冲突，
   每轮实现/验证都以 `int(time.time())` 时间戳新建分支——一个 spec 经数轮重试自然留下 4~6 条分支。
2. **销毁序列刻意保分支**：`core/worktree_manager/legacy_registry.py` 在 preserve/保留场景
   明确「不删分支（分支承载首轮已提交成果，绝不能 branch -D）」；`cleanup_stale_worktrees`
   只清 worktree 目录，分支 ref 全部留档。

现有可复用资产：
- `stale_sweep.py` 已有清扫节奏、锁、边扫边删防护、`_branch_protected_by_state` 状态保护；
- `queries.py` 已有 `_spec_from_branch` / `find_branches_by_spec` / `branch_exists`；
- `legacy_registry.py:838` 已有「删分支前同 spec 再登记复核」先例；
- 已merge 分支批量删除的零风险口径在本次人工清理中实证（2039 条 `-d` 全数成功）。

## Goals / Non-Goals

**Goals:**
- 分支数量收敛：merge-back 后的分支在宽限期后被自动回收，存量不再单调增长
- 零内容风险：只删已并入 main 的分支，`-d` 语义为硬边界
- 不破坏任何读分支的既有流程（deliverables D1 兜底、验证 diff 参照）
- 配置可见可控：Dashboard 有开关与宽限期界面

**Non-Goals:**
- **不做 merge-back 后立即删除**：deliverables 的 D1 解析在合并后仍可能
  `git show <branch>:tasks.md`，立即删除会收窄读取窗口；宽限期 GC 已足够收敛
- **不做未合并分支自动回收**：git cherry 补丁等价检测慢且「补丁等价≠内容已采纳」，
  留人工甄别；GC 仅在日志中报未合并计数
- **不做备份 ref 归档**：`-d` 口径下提交仍从 main 可达，备份 ref 只是把膨胀换名字
- **不改每轮新分支命名**：时间戳命名是并发正确性设计，与回收正交
- **不处理 `fenix/` 前缀之外的遗留分支**（如个别历史 `impl-*` 分支），留人工

## Decisions

1. **GC 挂在 stale_sweep 而非独立定时器**：复用既有清扫触发点、锁与「先快照后删除」防护，
   不引入新的调度面。worktree 清扫与分支清扫天然同源（同一批分支的生命周期两段）。
   触发形态取证（stale_sweep.py:38-41、legacy_registry.py:654、fenixd.py:883 唯一调用点）：
   `cleanup_stale_worktrees` 仅由 daemon 启动路径调用一次、无周期调度——GC 实际形态是
   「每次 daemon 启动回收一轮」而非周期定时；收敛性依赖 daemon 重启节奏，与 legacy
   宽限期兜底回收的既定姿态一致（长驻运行期间新增的已合并分支留待下次启动回收）。

2. **四条件判定，缺一不删**：merged + tip 早于宽限期 + 无 worktree 占用 + spec 非活跃。
   spec 活跃豁免 = 两守卫并集：(i) `_branch_protected_by_state` 在飞引用保护（branch 字段
   引用 / implementing 命名空间精确归属 / 冻结保持；单一来源复用，不复制常量）；
   (ii) spec 名解析 → STATE.md 显式状态判定，状态 ∈ 活跃状态集（implementing / implemented /
   testing / reviewing / ready(+_recovery_resume) / blocked(+frozen+_frozen_hold)）即豁免。
   取证：`_branch_protected_by_state` 的保护集不含 reviewing（stale_sweep.py:411 状态元组、
   (b) 仅查 implementing），而 reviewing 属 STATE 活跃状态——reviewing spec 的已合并分支若
   只靠 (i) 会在合并超宽限期后被误收，(ii) 为其补齐（宁漏勿误）。合并判定基线走既有
   `resolve_base_branch`（origin/HEAD → main → master 回退），不以硬编码 main 使 master
   基线仓库整轮 GC 失效。另：分支命中在册 recovery legacy 登记（`_legacy`，宽限期内同分支
   再登记含在内）时跳过——避免 GC 与 consume_legacy / _reclaim_expired_legacy 竞争同一分支，
   防「续做」降级为从零重派（对齐 legacy_registry.py:838 复核先例与 freeze-stop 保留语义）。

3. **删除只允许 `git branch -d`**：这是唯一的安全硬边界——扫描与删除之间若发生并发变化
   （如分支被新 worktree checkout、被 rebase 脱离 main），`-d` 会拒绝而非误删。
   由此最坏情况是漏删（下轮重扫），不存在丢内容路径。

4. **宽限期默认 7 天**：覆盖验证收尾后的 diff 参照窗口与 D1 读侧兜底窗口；经验上 spec 从
   merge-back 到归档极少超过 7 天。配置化后可按项目节奏调整。

5. **spec 非活跃判定**（配合决策 2 守卫 (ii)）：分支名 → spec 名（`_spec_from_branch` 口径：
   去前缀、末段纯数字时间戳、verify- 按验证分支语义剥离——GC 的目标是找回所属 spec，该
   helper 的既定选边正合适；queries.py 对「归属判定链」的 MUST NOT 复用警示针对的是
   「是否某 spec 的实现分支」这一不同问题，不适用本守卫）→ STATE.md 查状态；spec 不存在
   （已归档/已删除）视为非活跃。注意 `_spec_from_branch` 硬编码 `fenix/` 前缀
   （queries.py:82）：非 fenix 配置命名空间下的分支解析失败 → 按宁漏勿误跳过不删
   （仅漏删，无误删）。解析失败的分支一律跳过。

6. **配置形态 `worktree.branch_gc.{enabled,retention_days}`**：挂在 worktree 节下与
   GC 的宿主模块一致；默认开启（用户诉求即收敛，关闭是显式动作）；`retention_days`
   非法值回退默认 7（与 stale_code_selfheal 的容错口径一致）。

## Risks / Trade-offs

- **D1 读侧兜底窗口**：已合并分支 7 天后删除，`git show <branch>:tasks.md` 在此之后失效。
  影响面评估：D1 优先序为 worktree 内 tasks.md > branch > main；合并后 worktree 已清理、
  main 已有同内容文件，兜底落点自动滑到 main，读取结果等价。宽限期进一步覆盖长尾。
- **活跃状态集漂移**：STATE.md 新增活跃状态时若不同步 GC 的状态集，活跃分支可能被误收。
  缓解：守卫 (i) 取自 `_branch_protected_by_state` 单一来源（不复制常量），该处新增状态时
  GC 自动跟随；守卫 (ii) 的显式状态集为静态清单，STATE 新增活跃状态时 MUST 同步本设计与
  spec.md 的状态集枚举；spec 解析失败的分支默认跳过。
- **扫描开销**：`git branch --merged` 在万级分支下仍为毫秒级 ref 操作；每轮清扫多一次
  `for-each-ref` + 逐分支 tip 时间查询，量级可控（GC 只处理前缀家族命中分支）。
- **存量 116 条未合并分支不随本 SPEC 消失**：它们是历史 retry 中间态，自动机制不覆盖
  （设计取舍）；人工清理已在本次先行处置（保留 4 条甄别后需要保留的，其余 112 条已建
  `refs/fenix-branch-archive/20261027/*` 备份后删除）。
