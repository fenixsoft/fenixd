# recovery-legacy-check 增量规格

## ADDED Requirements

### Requirement: 死亡 run 遗产保留
实现 run 死亡（进程消失且未产出成功结果）触发恢复重派时，系统 MUST 将死亡 run 的 worktree 目录与分支注册为该 spec 的遗产（legacy），保留至「后继 run 成功 merge」或「宽限期超时」二者先到；遗产保留期间孤儿清扫器 MUST NOT 回收它。

#### Scenario: 死亡后遗产在册
- **GIVEN** run a1（worktree W1，分支 B1，含未提交变更）死亡
- **WHEN** 恢复链路重派 a2
- **THEN** W1/B1 注册为 a2 的遗产，清扫器跳过回收
- **AND** a2 成功 merge 后 W1/B1 按既有路径回收

#### Scenario: 宽限期兜底
- **GIVEN** 遗产注册后后继 run 迟迟未派发（如全链冷却）
- **WHEN** 宽限期（跟随孤儿清扫周期）超时
- **THEN** sweeper 兜底回收遗产并记审计日志

### Requirement: 遗产上下文注入
恢复重派的 implementer 任务书 prompt MUST 注入遗产上下文：遗产 worktree 绝对路径、分支名、`git status --short` 快照（脏文件清单，截断至合理长度）。无遗产（首次实现或遗产已被兜底回收）时 MUST NOT 注入空遗产段。

#### Scenario: 新 run 可见遗产
- **GIVEN** a1 死亡遗留 W1（脏文件 3 个）
- **WHEN** a2 启动
- **THEN** 其任务书含 W1 路径、分支名与 3 个脏文件清单
- **AND** 明确指示「W1 为只读参考，不得在其中工作」

### Requirement: agent 自主收编决策
新 run agent MUST 被赋予收编决策权：inspect 遗产后选择「收编」（把有价值的半成品移植进自己的 worktree 并在提交信息注明来源分支）或「弃用」（在任务书响应中声明重做理由）。框架 MUST NOT 强制其中一种选择，MUST NOT 担保遗产内容正确性。

#### Scenario: 收编路径
- **WHEN** a2 判定 W1 中半成品有价值
- **THEN** a2 将其复制进自己的 worktree、适配后提交，提交信息含「salvaged from B1」
- **AND** 验证链照常验收 a2 的产出（不因收编豁免）

#### Scenario: 弃用路径
- **WHEN** a2 判定遗产为破碎半成品
- **THEN** a2 从干净状态重做，并在产出说明中注明弃用理由

### Requirement: 只读边界
遗产 worktree 在遗产期内 MUST 为只读参考：恢复重派 MUST NOT 复用遗产 worktree 作为新 run 的工作目录（新建 worktree 的既有行为不变），锁与派发互斥逻辑不因遗产改变。

#### Scenario: 不派发进遗产
- **WHEN** a2 派发
- **THEN** a2 获得全新 worktree（与现状一致）
- **AND** 遗产 W1 不出现在任何可派发/可锁定清单中
