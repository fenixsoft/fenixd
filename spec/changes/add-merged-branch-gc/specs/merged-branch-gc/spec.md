## ADDED Requirements

### Requirement: 已合并分支定期回收

worktree 陈旧清扫（stale_sweep）MUST 在每轮清扫中包含已合并分支 GC 环节：扫描实现/验证分支
前缀家族（默认 `fenix/`）下的分支，对同时满足以下全部条件的分支执行 `git branch -d` 删除：

1. 分支已完全并入 main（`--merged` 口径）；
2. 分支 tip 提交时间早于宽限期（`worktree.branch_gc.retention_days`，默认 7 天）；
3. 分支未被任何已登记 worktree checkout；
4. 分支所属 spec 在 STATE.md 中不存在或处于非活跃状态（状态保护口径与既有
   worktree 清扫的 `_branch_protected_by_state` 一致）。

删除动作 MUST 只使用 `git branch -d`（拒绝未合并分支的删除语义），MUST NOT 使用 `-D`。
GC MUST 在既有清扫锁内执行；GC 关闭（`worktree.branch_gc.enabled: false`）时 MUST 完全跳过。

#### Scenario: 四条件齐备的分支被回收

- **WHEN** 存在分支 `fenix/add-old-feature-1787000000`，已完全并入 main，tip 提交于 10 天前，
  无 worktree checkout，spec 已归档（非活跃）
- **THEN** GC 执行 `git branch -d fenix/add-old-feature-1787000000` 且删除成功

#### Scenario: 宽限期内分支保留

- **WHEN** 分支已并入 main 但 tip 提交于 3 天前（retention_days=7）
- **THEN** 该分支本轮 GC 不被删除，下轮清扫继续评估

#### Scenario: 未合并分支永不进入删除

- **WHEN** 存在未并入 main 的 `fenix/*` 分支（无论多旧）
- **THEN** GC 不对其执行任何删除动作（`-d` 语义天然拒绝，且扫描阶段即排除），
  未合并分支数量计入日志计数但不删

#### Scenario: GC 关闭时零动作

- **WHEN** `worktree.branch_gc.enabled` 为 false
- **THEN** 清扫轮不执行分支扫描与删除，行为与引入 GC 之前完全一致

### Requirement: 活跃 spec 分支豁免

分支所属 spec 处于活跃状态（ready / implementing / testing / reviewing 等 STATE.md 活跃
状态集）时，GC MUST 跳过该分支，无论合并状态与 tip 新旧。spec 名从分支名解析（剔除前缀与
时间戳后缀），解析规则 MUST 与 `_spec_from_branch` 现有口径一致。

#### Scenario: 活跃 spec 的已合并分支保留

- **WHEN** spec `add-command-center` 状态为 testing，其某轮分支 `fenix/add-command-center-<ts>`
  已并入 main 且 tip 超过宽限期
- **THEN** GC 不删除该分支（活跃豁免优先于合并判定）

#### Scenario: worktree 占用分支跳过

- **WHEN** 分支被某个已登记 worktree checkout（如 fast-track 保留复用场景）
- **THEN** GC 跳过该分支，不产生删除报错

### Requirement: 分支 GC 配置与 Dashboard 界面

配置新增 `worktree.branch_gc` 节：`enabled`（bool，默认 true）与 `retention_days`（int，
默认 7，最小值 1）。配置键 MUST 与 Dashboard 设置页界面同步提供：设置页新增分支 GC 面板，
含开关与宽限期天数输入，保存走既有配置写回通道。缺省值必须在配置模板
（`.fenix/config.template.yaml`）中带注释说明。

#### Scenario: 配置缺省即开启

- **WHEN** 用户配置中不存在 `worktree.branch_gc` 节
- **THEN** GC 按默认参数（enabled=true, retention_days=7）运行，日志可见 GC 生效

#### Scenario: 非法配置不致崩

- **WHEN** `retention_days` 配置为 0 或负数或非整数
- **THEN** 配置解析按无效值处理（回退默认 7），不抛异常、不中断清扫轮

#### Scenario: Dashboard 面板读写配置

- **WHEN** 用户在 Dashboard 设置页修改分支 GC 开关或宽限期并保存
- **THEN** 配置经既有写回通道落盘并生效（热更新机制覆盖），面板重新打开时回显当前值

### Requirement: GC 运行可观测

每轮执行了删除的 GC MUST 在日志中记录：删除的分支名清单、删除总数、跳过计数
（未合并 / 宽限期内 / 活跃 spec / worktree 占用各一档）。零删除 MUST 静默（不产日志噪音）。
GC 异常（如 git 命令失败）MUST 与既有清扫环节同口径——单分支失败不中断整轮清扫，
失败分支留待下轮。

#### Scenario: 有删除时输出结构化日志

- **WHEN** 某轮 GC 删除了 3 条分支、另有 2 条因宽限期内跳过
- **THEN** 日志包含删除清单（3 个分支名）、删除数 3、跳过-宽限期计数 2

#### Scenario: 单分支删除失败不中断清扫

- **WHEN** 某分支 `git branch -d` 因并发 worktree 注册新 checkout 而失败
- **THEN** 记录该分支失败明细，继续处理其余分支，清扫轮正常完成
