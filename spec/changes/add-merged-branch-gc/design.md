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

1. **GC 挂在 stale_sweep 而非独立定时器**：复用既有清扫节奏、锁与「先快照后删除」防护，
   不引入新的调度面。worktree 清扫与分支清扫天然同源（同一批分支的生命周期两段）。

2. **四条件判定，缺一不删**：merged + tip 早于宽限期 + 无 worktree 占用 + spec 非活跃。
   活跃状态集与 `_branch_protected_by_state` 同口径，不另立标准。

3. **删除只允许 `git branch -d`**：这是唯一的安全硬边界——扫描与删除之间若发生并发变化
   （如分支被新 worktree checkout、被 rebase 脱离 main），`-d` 会拒绝而非误删。
   由此最坏情况是漏删（下轮重扫），不存在丢内容路径。

4. **宽限期默认 7 天**：覆盖验证收尾后的 diff 参照窗口与 D1 读侧兜底窗口；经验上 spec 从
   merge-back 到归档极少超过 7 天。配置化后可按项目节奏调整。

5. **spec 非活跃判定**：分支名 → spec 名（剔除前缀与时间戳后缀，`_spec_from_branch` 口径）
   → STATE.md 查状态；spec 不存在（已归档/已删除）视为非活跃。解析失败的分支一律跳过
   （宁漏勿误）。

6. **配置形态 `worktree.branch_gc.{enabled,retention_days}`**：挂在 worktree 节下与
   GC 的宿主模块一致；默认开启（用户诉求即收敛，关闭是显式动作）；`retention_days`
   非法值回退默认 7（与 stale_code_selfheal 的容错口径一致）。

## Risks / Trade-offs

- **D1 读侧兜底窗口**：已合并分支 7 天后删除，`git show <branch>:tasks.md` 在此之后失效。
  影响面评估：D1 优先序为 worktree 内 tasks.md > branch > main；合并后 worktree 已清理、
  main 已有同内容文件，兜底落点自动滑到 main，读取结果等价。宽限期进一步覆盖长尾。
- **活跃状态集漂移**：STATE.md 新增活跃状态时若不同步 GC 的状态集，活跃分支可能被误收。
  缓解：状态集取自 `_branch_protected_by_state` 单一来源（不复制常量），该处新增状态时
  GC 自动跟随；spec 解析失败的分支默认跳过。
- **扫描开销**：`git branch --merged` 在万级分支下仍为毫秒级 ref 操作；每轮清扫多一次
  `for-each-ref` + 逐分支 tip 时间查询，量级可控（GC 只处理前缀家族命中分支）。
- **存量 116 条未合并分支不随本 SPEC 消失**：它们是历史 retry 中间态，自动机制不覆盖
  （设计取舍）；人工清理已在本次先行处置（保留 4 条甄别后需要保留的，其余 112 条已建
  `refs/fenix-branch-archive/20261027/*` 备份后删除）。
