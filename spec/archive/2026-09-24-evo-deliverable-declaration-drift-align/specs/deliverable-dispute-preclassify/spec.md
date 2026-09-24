# Requirement: 交付物声明漂移笔误机械对齐

## ADDED Requirements

### Requirement: 漂移笔误机械对齐

交付物守卫缺件异议时，若满足以下条件，系统 MUST 机械对齐声明并解除 blocked：
1. 声明路径在主树与实现分支 HEAD 均不存在（git cat-file / 文件系统核实）
2. git 历史对该路径有命中（git log --all -- <path> 非空，即该文件曾存在——拆包/改名漂移特征，区别于零引用孤儿）
3. 候选新落点可唯一定位（如 core/worktree_manager.py → core/worktree_manager/mergeback.py 唯一候选）

候选定位 MUST 为确定性规则，MUST NOT 依赖函数名或任何非字面证据：候选 = 旧路径 basename 去 `.py` 所得包目录内、且落在本次实现分支改动集合（`git diff --name-only --diff-filter=AM <merge-base>..<branch>`）内的 `.py` 文件；MUST NOT 用全仓 rglob 同名文件兜底（同名文件会伪造唯一性）。交集唯一且该路径在实现分支 HEAD 真实存在（`file_exists_on_branch`）方判可对齐。

本通道 MUST 复用既有原语，MUST NOT 另起一套：陈日信号 `is_stale_declaration`、生效声明解析 `resolve_effective_declaration`（`Dispatcher._effective_declaration`）、改写 `relocate_declared_path`、凭据 `register_relocation_credential`。与 `_preclassify_stale` 通道互斥：同一轮同一 spec MUST NOT 由两条通道各改写一次声明（本通道失败即回退既有人工通道，MUST NOT 再触发重定位改写）。

对齐动作：改写**生效声明所在位置**的 tasks.md Deliverables 段 path 为实际落点（生效声明来源为分支版本、无落盘位置时改走凭据登记，MUST NOT 直写主树声明——改写与守卫读取错位即本 SPEC 立项根因），改写后立即提交该文件以防 merge 死锁；写入 dispute audits 记录（`verdict=drift-aligned`、`actual_path`、判断依据，同时以 `type=relocation` 形态落册以命中收缩防护的重定位凭据豁免）；解除 blocked 后自动重入实现。

任一环节异常（生效声明不可读、条目不存在、候选零个或多个、改写或提交失败）MUST fail-open 回既有 blocked 待人工通道，MUST NOT 半途改写。

#### Scenario: 唯一落点机械对齐

- **GIVEN** 异议路径 core/worktree_manager.py 在主树与分支 HEAD 均缺、git 历史命中，且实现分支改动集合中 core/worktree_manager/ 包内恰有 1 个 `.py` 文件（该路径在分支 HEAD 存在）
- **WHEN** 守卫处理该异议
- **THEN** 生效声明的声明段被机械改写为该落点、改写文件已提交，审计记录含 verdict=drift-aligned/actual_path/type=relocation，blocked 解除、实现自动重入

#### Scenario: 候选不唯一或不可达回人工

- **GIVEN** 实现分支改动集合与包目录内文件交集为零个或两个及以上；或声明生效来源为分支版本（无落盘位置）；或候选路径在实现分支 HEAD 不存在
- **WHEN** 守卫处理该异议
- **THEN** 不机械改写，维持既有走人工通道（fail-open），与现状行为一致

## Requirement 2: 派发前同源草案收敛检查

implementer/fast-track 派发前（`_on_spec_ready`，且队列候选筛选入口同样覆盖），系统 MUST 检查本 spec 目录自身是否含 `SUPERSEDED.md`（已被取代，不再作为独立实现入口）：命中 → 禁止派发、spec 置 blocked（error=同源草案收敛义务未满足，附 SUPERSEDED.md 路径），待收敛（该 SUPERSEDED.md 移除或目录删除）后恢复。

同源判定 MUST 以「显式点名」（目录名以 inline code / 路径形态出现在 SUPERSEDED.md 正文）与「本目录自身含 SUPERSEDED.md」为判据；MUST NOT 依赖 `.spec.yaml` 的 capability 字段（实测全仓无该键）；MUST NOT 仅因「平级存在名字归一后相同的草案」就拦截——被 SUPERSEDED.md 点名的**生效落点**与收敛源按名字归一会互为命中，误拦会把生效草案永久冻住。

#### Scenario: 被取代草案双 run 拦截

- **GIVEN** evo-merge-back-wip-overlap-gate 目录含 SUPERSEDED.md（声明 -575976 为生效落点）
- **WHEN** 派发 implementer/fast-track 于 evo-merge-back-wip-overlap-gate
- **THEN** 派发被拦截、spec 置 blocked 并指向 SUPERSEDED.md；-575976（生效落点，自身无 SUPERSEDED.md）正常派发

#### Scenario: 收敛完成后恢复派发

- **GIVEN** 被取代目录的 SUPERSEDED.md 已被移除（或目录已删除）
- **WHEN** 再次派发该 spec
- **THEN** 不再拦截，按既有派发流程执行

## Requirement 3: 审计留痕

机械对齐 MUST 留审计：dispute_audits 记录含 instrument 路径、actual_path、候选唯一性证据（如 git 历史命中数、候选清单）、判据（drift-aligned）；fail-open 回人工的异议 MUST 带「存在漂移特征但无法唯一定位」的说明，供人工快速裁决。