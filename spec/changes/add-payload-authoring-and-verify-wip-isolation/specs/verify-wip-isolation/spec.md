# Spec Delta: verify-wip-isolation

## ADDED Requirements

### Requirement: 验证轮主树 WIP 重叠预检

每个验证轮（prepare/serve/场景命令执行）启动时 MUST 预检主树工作区状态：收集未提交改动（dirty tracked 口径单源复用 core/worktree_manager/queries.py 既有 porcelain 解析供给），判定其与验证涉及路径的重叠（构建输入：prepare 涉及模块、场景命令引用路径；判定口径与 merge-back WIP overlap gate 一致——`_detect_wip_overlap`（core/worktree_manager/mergeback.py:907）的 dirty∩改动面口径与 `spec/changes/**` 排除先例（`MergeConflictInfo.wip_overlap` core/worktree_manager/types.py:206、autostash `:(exclude)spec/changes` core/worktree_manager/stash_guard.py:205）；`.fenix/` 运行时产物为 gitignore 未 tracked、`spec/changes/**` 属排除面，均不参与预检）。无重叠或主树干净时验证轮 MUST 完全维持现有行为（原地构建执行，零新增开销路径）。检出重叠时验证引擎 MUST 进入隔离决策（下一条需求），MUST NOT 直接在污染主树上构建计数。

#### Scenario: 主树干净零回归
- **WHEN** 验证轮启动时 git status --porcelain 为空（或仅含排除面条目）
- **THEN** 验证轮按现有流程原地执行，报告与轮次计数行为与现状逐字节一致，无额外 worktree 创建

#### Scenario: 重叠检出进入隔离决策
- **WHEN** 验证轮启动时主树存在未提交改动且涉及构建输入路径（如 source/ 下 Kotlin 文件半成品）
- **THEN** 验证引擎记录重叠清单并转入隔离执行或跳过决策，本轮 MUST NOT 直接以污染工作区产出计入验证失败

### Requirement: 重叠时优先干净 worktree 隔离执行

检出重叠时验证引擎 MUST 优先尝试干净 worktree 隔离执行：从 HEAD 创建（或复用既有验证 worktree）后，在其中执行 prepare、serve 与全部场景命令，报告 MUST 标注 verify_root（主树/隔离 worktree 路径）留痕。隔离执行 MUST NOT stash、checkout 或以任何方式改动用户主树工作区。隔离执行的结果计数与判分语义 MUST 与原地执行完全一致（judge 归因、轮次计数、断言评估不因 verify_root 不同而改变）。

#### Scenario: 隔离 worktree 构建验证
- **WHEN** 主树存在交互会话 boot-recovery 半成品 WIP 且验证轮预检检出重叠
- **THEN** 引擎从 HEAD 创建干净 worktree 执行构建与场景命令，主树 WIP 文件字节不动，报告 verify_root 标注隔离路径，构建结果按 worktree 真实状态判分

#### Scenario: 主树 WIP 字节级不动
- **WHEN** 隔离执行全流程运行（含 prepare 构建产物生成）
- **THEN** 主树工作区 git status --porcelain 输出在验证轮前后完全一致，无 stash、无 checkout、无构建产物落入主树

### Requirement: 隔离不可行时跳过不计数

干净 worktree 隔离不可行时（worktree 创建失败、磁盘不足、HEAD 本身不可构建等），验证引擎 MUST 跳过本轮：本轮 MUST NOT 计入验证失败轮数、MUST NOT 递增 `_env_block_rounds`、MUST NOT 触发 env 阻塞冻结升级（escalation.py ENV_BLOCK_FREEZE_THRESHOLD 判定不得因本类跳过推进），MUST 记录 info 级留痕（跳过原因 + 重叠清单）。跳过不得阻塞调度器其他 SPEC 的验证轮。归因 MUST 区分「主树 WIP 重叠导致的跳过」与真实环境失败——前者是框架隔离决策，非被测对象缺陷。

#### Scenario: 创建失败跳过留痕
- **WHEN** 隔离 worktree 创建失败（如磁盘不足）
- **THEN** 本轮标记 skipped（原因=wip_overlap_isolation_unavailable），失败轮数与 _env_block_rounds 均不变，info 留痕含重叠文件清单，调度器继续派发其他 SPEC

#### Scenario: 不据此冻结
- **WHEN** 连续多轮均因主树 WIP 重叠且隔离不可行而跳过
- **THEN** 系统不升级冻结、不派发 admin 告警（WIP 归因保持 info 留痕），主树 WIP 消除后下一轮自动恢复正常计数

### Requirement: WIP 归因展示

报告与 judge 归因 MUST 将隔离执行轮标注为「主树 WIP 存在，已在隔离 worktree 验证」；跳过轮标注为「主树 WIP 重叠，验证跳过不计数」。两类标注均为 info 级，MUST NOT 计入任何失败/阻塞计数，MUST NOT 产生 require-admin 处置告警。

#### Scenario: 报告标注可读
- **WHEN** 用户查看隔离执行轮或跳过轮的验证报告
- **THEN** 报告头部呈现 verify_root 与 WIP 标注（info 级），判分明细中不出现因 WIP 产生的伪失败条目
