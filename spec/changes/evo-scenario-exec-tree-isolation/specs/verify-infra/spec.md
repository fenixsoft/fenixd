# verify-infra Specification

## ADDED Requirements

### Requirement: pytest/cli 执行集执行树隔离

验证执行根决策对「无 serving worktree 条件且执行集含 pytest/cli 类场景」SHALL 创建一次性快照 worktree 作为执行根并在执行后清理；主树仅作为快照不可行时的回退且 SHALL 留痕。scenario-repaired 重入、排程重验、unfreeze 重验共用同一决策点，SHALL 一并覆盖。

#### Scenario: 执行窗内主树被改写不影响结果

- **WHEN** pytest/cli 场景执行期间主树被任意车道 merge-back 改写
- **THEN** 执行读取的是快照 worktree，源码锚位断言不受影响，不产生锚位错位假失败

### Requirement: 验证执行与 merge-back 互斥

merge-back SHALL 在启动前探测验证执行在飞：在飞时有界等待/推迟，超时放行并告警留痕；不并发读写主树，不改 WIP 重叠 precheck 既有语义。

#### Scenario: merge-back 等待验证收尾

- **WHEN** merge-back 启动时探测到验证执行在主树在飞
- **THEN** merge-back 有界推迟至执行收尾，超时则放行并告警留痕

### Requirement: 源码锚位失败稳态复跑

全量回归类场景出现源码锚位类断言失败时，SHALL 对失败用例子集自动做一次稳态复跑：复跑通过按瞬态留痕处理（不计 fail、不驱动 judge 重跑），复跑仍败按真实失败进入既有链路。

#### Scenario: 锚位假失败被稳态复跑甄别

- **WHEN** 锚位断言失败且稳态复跑通过
- **THEN** 该场景按瞬态留痕处理，验证结果不含该假失败，judge 不因它重跑