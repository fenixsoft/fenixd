# Requirement: 交付物声明漂移笔误机械对齐

## Requirement 1: 漂移笔误机械对齐

交付物守卫缺件异议时，若满足以下条件，系统 MUST 机械对齐声明并解除 blocked：
1. 声明路径在主树与实现分支 HEAD 均不存在（git cat-file / 文件系统核实）
2. git 历史对该路径有命中（git log --all -- <path> 非空，即该文件曾存在——拆包/改名漂移特征，区别于零引用孤儿）
3. 全仓可唯一定位候选新落点（如 core/worktree_manager.py → core/worktree_manager/mergeback.py 唯一候选）

对齐动作：改写 tasks.md Deliverables 声明段 path 为实际落点，写入 dispute audits 记录（verdict=drift-aligned、actual_path、判断依据），解除 blocked 后自动重入实现。

### Scenario: 唯一落点机械对齐

- **GIVEN** 异议路径 core/worktree_manager.py 在主树与分支 HEAD 均缺、git 历史命中、全仓扫描唯一候选 core/worktree_manager/mergeback.py
- **WHEN** 守卫处理该异议
- **THEN** 声明段被机械改写为 core/worktree_manager/mergeback.py，审计记录 verdict=drift-aligned 落盘，blocked 解除、实现自动重入

### Scenario: 无法唯一定位回人工

- **GIVEN** 候选取证失败（候选零个或两个及以上）
- **WHEN** 守卫处理该异议
- **THEN** 不机械改写，维持既有走人工通道（fail-open），与现状行为一致

## Requirement 2: 派发前同源草案收敛检查

implementer 派发前（_on_spec_ready），系统 MUST 检查同源草案收敛状态：
- 存在其它 spec 目录的 SUPERSEDED.md 声明本 spec 为已取代草案（同需求收敛标记）；或
- 本 spec 目录自身含 SUPERSEDED.md（已被取代）

命中任一 → 禁止派发 implementer，spec 置 blocked（error=同源草案收敛义务未满足，附 SUPERSEDED.md 路径），待收敛（更新/删除旧草案）后恢复。

### Scenario: 同源草案双 run 拦截

- **GIVEN** evo-merge-back-wip-overlap-gate 未收敛、其 SUPERSEDED.md 声明 -575976 为生效落点
- **WHEN** 派发 implementer 于 evo-merge-back-wip-overlap-gate
- **THEN** 派发被拦截、spec 置 blocked 并指向 SUPERSEDED.md；-575976 正常派发

## Requirement 3: 审计留痕

机械对齐 MUST 留审计：dispute_audits 记录含 instrument 路径、actual_path、候选唯一性证据（如 git 历史命中数、候选清单）、判据（drift-aligned）；fail-open 回人工的异议 MUST 带「存在漂移特征但无法唯一定位」的说明，供人工快速裁决。