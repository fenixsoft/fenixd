# spec-mergeback-inplace-repair

## ADDED Requirements

### Requirement: 语义冲突失败进入 repair 通道
implementer merge-back 失败且产物自愈与 ignored-DU 自愈均不适用（冲突含语义文件）时，Fenixd MUST 进入 repair 通道：保留实现分支及其工作现场，派 repair agent 原地修复，而非 abort 后全新重派。全部冲突路径均为构建产物且自愈成功时，MUST NOT 派发 repair agent（自愈即收口）。

#### Scenario: 语义冲突触发 repair
- **WHEN** implementer merge-back 失败，冲突含 src 语义文件，产物自愈返回 False
- **THEN** 实现分支保留、主树 abort 保持干净，spec 进入 repair 流程派发 repair agent，而非立即全新重派

#### Scenario: 产物自愈适用时不触发 repair
- **WHEN** merge-back 失败但全部冲突路径位于构建产物目录，自愈对齐完成 merge
- **THEN** merge 正常完成，不进入 repair 通道

### Requirement: 修复方向反转与主树干净态
repair agent MUST 在实现分支一侧修复：把 main merge 进分支并解决冲突后 commit。派发 repair 前框架 MUST 保证主树处于 merge abort 后的干净态。repair 期间主树无需冻结：其他 spec 的 merge-back 可照常推进主树；repair 完成后的 re-merge-back 若因主树再度前进产生新冲突，按既有冲突处理路径与熔断计数处理。

#### Scenario: 主树保持干净
- **WHEN** repair agent 被派出
- **THEN** 主树无半合并状态残留（未合并条目、MERGE_HEAD 等均不存在）

#### Scenario: repair 完成后重推
- **WHEN** repair agent 已把 main 合入分支并提交冲突解决
- **THEN** 框架对该分支重新执行 merge-back，分支含 main 历史应快速前进

### Requirement: 分支载体三态
repair 以实现分支为载体，按现场存活状态三态处理：(a) 原 worktree 存在 → 原地进入该 worktree，未跟踪构建资产（node_modules、构建缓存）保留；(b) worktree 已清理但分支存在 → 在该分支上创建新 worktree 进入；(c) 分支不存在（已并入主树或已清扫）→ 回退 fallback：从 main 新建 worktree 全新重派，prompt 注入 merge 失败上下文。

#### Scenario: 原 worktree 在场原地修复
- **WHEN** merge-back 失败且实现 worktree 目录仍存在
- **THEN** repair agent 在该 worktree 内工作，worktree 内未跟踪文件不被清理重建

#### Scenario: 仅分支存活换壳修复
- **WHEN** worktree 已被清理但实现分支 fenix/&lt;spec&gt;-&lt;ts&gt; 存在
- **THEN** 在该分支上创建新 worktree，repair agent 进入修复，修复成果随分支 merge-back

#### Scenario: 分支消亡回退重派
- **WHEN** 实现分支不存在（已被合并进主树或被清扫）
- **THEN** 走 fallback：从 main 新建 worktree 正常重派 implementer，prompt 注入 merge 失败错误上下文

### Requirement: 遗产认领竞态防护
repair 认领登记在 `_legacy` 的 worktree/分支时，MUST 走与 fast-track 复用一致的 take 动作（认领时从 `_legacy` 摘出），保证孤儿清扫 sweeper 不在 repair 进行中按宽限期回收现场。

#### Scenario: repair 期间 sweeper 不回收
- **WHEN** repair agent 正在使用 `_legacy` 登记的 worktree/分支
- **THEN** 该条目已在认领时摘出登记表，sweeper 宽限期超时后仍不回收该现场

### Requirement: repair prompt 形态
repair prompt MUST 包含：spec 身份与实现目标简述、冲突文件清单摘要（来自 merge 输出与 git status）、修复方向说明（把 main 合入分支、解决冲突、运行测试、commit）。MUST NOT 注入原 worktree 地址等间接情报（agent 即在现场，冲突状态可自查）。repair agent 无法解决冲突时 MUST 显式输出失败结论，框架据此回退。

#### Scenario: prompt 无间接地址注入
- **WHEN** 构建 repair prompt
- **THEN** prompt 不包含"原 worktree 路径"类间接情报字段，冲突清单来自当次 merge 失败输出

#### Scenario: 修复失败显式回退
- **WHEN** repair agent 显式报告无法解决冲突，或 repair run 超时/失败
- **THEN** 框架回退 fallback 全新重派，原分支按既有清扫策略处理

### Requirement: repair 预算与轮次约束
repair 轮 MUST 计入该 spec 的实现预算（token 记在该 spec 名下）。同一 merge 失败事件链内 repair 最多 2 轮，超限后回退 fallback 重派，不再继续派 repair。

#### Scenario: repair 计费归 spec
- **WHEN** repair agent 消耗 token
- **THEN** 计入所属 spec 的实现预算统计，不记为独立 spec 消耗

#### Scenario: 超轮次回退
- **WHEN** 同一 merge 失败链内 repair 已进行 2 轮仍未完成可合并状态
- **THEN** 回退 fallback 全新重派，本轮失败链内不再派发 repair
