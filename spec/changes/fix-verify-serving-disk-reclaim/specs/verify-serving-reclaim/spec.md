## ADDED Requirements

### Requirement: serving worktree 无主回收判据

系统 SHALL 对 `.fenix/verify-serving/` 下的每个条目按「保留集」判定是否回收，
判据 MUST 满足 fail-safe：任一判据显示该条目可能仍被使用，MUST 保留。

目录条目 `<name>` 的保留条件（满足其一即保留）：

1. **归属 spec 存活**：`<name>` 能按 `{spec}-{10 位 Unix 时间戳}` 约定解析出
   spec 名，且该 spec 目录存在于 `spec/changes/` 或 `spec/archive/` 之下。
2. **登记在册**：`<name>` 的绝对路径出现在 `.fenix/verify-serving/servers.json`
   任一条目的 `worktree` 字段中。
3. **活进程占用**：进程表存在 argv 或 cwd 指向 `<name>` 的存活进程。
4. **近期新建宽限**：`<name>` 的创建/修改时间在宽限期内（防与并发创建竞态）。

四条皆不满足的目录条目 MUST 被回收。

#### Scenario: 归属 spec 仍在 changes 的目录保留

- **WHEN** `.fenix/verify-serving/fix-foo-1789587927` 的 spec 名 `fix-foo`
  存在于 `spec/changes/fix-foo/`
- **THEN** 该目录 MUST 保留，MUST NOT 被回收

#### Scenario: 归属 spec 已归档的目录保留

- **WHEN** `.fenix/verify-serving/add-bar-1788528914` 的 spec 名 `add-bar`
  仅存在于 `spec/archive/2026-09-04-add-bar/` 下
- **THEN** 该目录 MUST 保留（归档等同存活，便于回溯证据）

#### Scenario: spec 与登记双重消失的目录回收

- **WHEN** `.fenix/verify-serving/add-baz-1788583057` 的 spec 名 `add-baz`
  在 `spec/changes/` 与 `spec/archive/` 均不存在，且 servers.json 无该路径登记，
  且无活进程指向该目录
- **THEN** 该目录 MUST 被回收

#### Scenario: 无活进程但登记仍在的目录保留

- **WHEN** 目录的 spec 名在 changes/archive 均不存在，但 servers.json 仍登记该
  目录路径
- **THEN** 该目录 MUST 保留（登记优先于回收，避免误删在飞实例的工作区）

#### Scenario: 目录名不符合命名约定时保留

- **WHEN** `.fenix/verify-serving/` 下出现无法按 `{spec}-{10 位时间戳}` 解析的
  条目（如末段非 10 位时间戳）
- **THEN** 该条目 MUST 保留（无法判定归属时 fail-safe，MUST NOT 删除）

#### Scenario: 末段为短数字后缀的 spec 名正确解析

- **WHEN** 目录名形如 `evo-merge-back-wip-overlap-gate-575976-1789694112`
  （spec 名自身含 6 位数字后缀，末段方为 10 位时间戳）
- **THEN** 解析出的 spec 名 MUST 为 `evo-merge-back-wip-overlap-gate-575976`，
  并按该名判定存活

### Requirement: 清扫执行语义

系统 SHALL 通过 `git worktree remove --force` 回收无主 serving worktree，
并在回收后执行 `git worktree prune` 清理 git 侧的 worktree 登记。

回收为破坏性操作，MUST 满足：

- 单条目回收失败（git 命令非零退出、权限错误等）MUST 记 WARNING 日志并继续
  处理其余条目，MUST NOT 中断清扫整体或阻塞 daemon。
- 回收 MUST 幂等：目录已不存在时该条目 MUST 被安全跳过。
- 回收 MUST NOT 触碰 `servers.json`、`servers.json.lock`、`contract_selfcheck.json`
  等顶层状态文件。

#### Scenario: 回收后 git 登记同步清理

- **WHEN** 无主目录被 `git worktree remove --force` 回收
- **THEN** 系统 MUST 随后执行 `git worktree prune`，使
  `git worktree list` 不再包含该路径

#### Scenario: 单条目失败不阻塞其余

- **WHEN** 某个无主目录因 git 命令报错（如被外部进程占用）回收失败
- **THEN** 系统 MUST 记 WARNING 并继续回收同批其余无主目录

#### Scenario: 重复清扫幂等

- **WHEN** 对同一批条目连续执行两次清扫
- **THEN** 第二次 MUST 安全空转，MUST NOT 报错

### Requirement: 清扫触发点

系统 SHALL 在 daemon **启动时**执行一次全量 reconcile，并复用既有 600s 周期
孤儿清扫节拍执行**周期性**清扫。

启动 reconcile MUST 覆盖 `use_in_flight=False` 语义（daemon 重启后前一轮实例
视为非在飞），周期清扫 MUST 覆盖 `use_in_flight=True` 语义（保留 testing 中
spec 的目录）。

#### Scenario: 启动即回收存量孤儿

- **WHEN** daemon 启动，`.fenix/verify-serving/` 存在前一轮遗留的无主目录
- **THEN** 启动 reconcile MUST 在本轮启动内回收它们

#### Scenario: 周期清扫兜底运行期孤儿

- **WHEN** daemon 已运行且距上次孤儿清扫达 600s 节拍
- **THEN** 系统 MUST 执行一次 serving 目录清扫

#### Scenario: 启动清扫失败不阻塞启动

- **WHEN** 启动 reconcile 抛异常
- **THEN** 系统 MUST 记 ERROR 日志并继续 daemon 启动流程

### Requirement: boot.log 回收

系统 SHALL 按与目录相同的「无主」判据回收 `.fenix/verify-serving/`
下的 `<spec>-boot.log`：其 spec 名在 `spec/changes/` 与 `spec/archive/`
均不存在且无在飞 run 时回收；否则保留。

#### Scenario: 无主 spec 的 boot.log 回收

- **WHEN** `.fenix/verify-serving/add-gone-boot.log` 的 spec 名 `add-gone`
  在 changes/archive 均不存在
- **THEN** 该文件 MUST 被删除

#### Scenario: 存活 spec 的 boot.log 保留

- **WHEN** `.fenix/verify-serving/evo-merge-back-wip-overlap-gate-575976-boot.log`
  的 spec 存在于 `spec/changes/`
- **THEN** 该文件 MUST 保留

#### Scenario: 无法解析归属的 boot.log 保留

- **WHEN** `.fenix/verify-serving/contract_selfcheck.json` 或名称不含可解析
  spec 名的文件
- **THEN** 该文件 MUST 保留（fail-safe，MUST NOT 删除）

### Requirement: 清扫可观测性

系统 SHALL 在清扫后输出可观测记录：回收条目数与保留条目数。

#### Scenario: 清扫输出回收统计

- **WHEN** 一次清扫回收了 N 个目录条目
- **THEN** 系统 MUST 记录包含回收数量的日志（或返回值），供 dashboard / 运维
  追溯
