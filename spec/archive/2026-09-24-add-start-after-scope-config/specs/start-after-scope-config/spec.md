# start-after-scope-config — start_after 门控覆盖范围配置

## ADDED Requirements

### Requirement: start_after 门控覆盖范围配置键

系统 SHALL 提供配置键 `gates.start_after_scope`（枚举 `full` / `dispatch`），声明
`start_after` 未到期（含哨兵 `manual`）的 SPEC 除实现派发外，是否**同时**被按住晋升与
评审入口。缺省值 MUST 为 `dispatch`。

- `dispatch`（缺省）：`start_after` **只**约束实现派发链——`drafted` SPEC 照常被自动晋升
  （`drafted → ready` 或按方案评审分流 `drafted → reviewing`），方案评审活动立即进行；
  实现派发仍等到期/激活（`fix-start-after-premature-pickup` 之前的行为）。
- `full`：`start_after` 同时约束晋升入口、评审入口与对应恢复分支——SPEC 停留 `drafted`，
  直到到期/激活才晋升并起评审（`fix-start-after-premature-pickup` 之后的行为）。

配置校验 SHALL 拒绝非枚举值并在加载时报错，错误信息 MUST 指出合法取值。该键 MUST 纳入
Dashboard 受管配置键白名单，支持经设置页「审批」页签读写、用户级→项目级同步与配置热更新
（30s mtime 原地重载），无需重启 daemon。

#### Scenario: 缺省值为 dispatch
- **WHEN** 配置文件中不存在 `gates.start_after_scope` 键
- **THEN** getter 返回 `dispatch`，定时 SPEC 立即晋升并起评审，仅实现派发等到期

#### Scenario: 显式 full
- **WHEN** 配置文件中 `gates.start_after_scope` 为 `full`
- **THEN** getter 返回 `full`，定时 SPEC 停留 `drafted`，晋升与评审一并等到期/激活

#### Scenario: 非法值被拒
- **WHEN** 配置文件中 `gates.start_after_scope` 为 `"sometimes"` 或其它非枚举值
- **THEN** 配置加载校验失败并给出明确错误信息，指出合法取值为 full/dispatch

#### Scenario: 设置页读写与热更新
- **WHEN** 用户在设置页「审批」页签选择覆盖范围并保存
- **THEN** 值持久化到对应配置层（用户级/项目级按现有受管键规则），daemon 在热更新窗口内
  感知新值，无需重启

### Requirement: scope 同时作用于定时值与 manual 哨兵

`gates.start_after_scope` SHALL 作用于 `start_after` 取值域**全部阻塞态**——具体未来时间与
哨兵 `manual` 一律按当前 scope 决定是否按住晋升/评审入口。MUST NOT 只对定时值生效而让
`manual` 哨兵恒定按住晋升。

`manual` 哨兵在 `dispatch` 档下的语义 MUST 表述为：SPEC 立即晋升并（按评审判定）起评审，
评审通过后停在 `ready`，由实现派发口的无条件 `start_after` 门拦住不实现，直到人工激活
（`start_after` 置 null）。即**哨兵「不自动实现」的保证恒成立**，变的只是「是否提前跑评审」。

#### Scenario: dispatch 档下 manual 哨兵提前评审但不实现
- **WHEN** `start_after_scope` 为 `dispatch`，SPEC 为 `drafted` 且 `start_after` 为 `manual`
- **THEN** 该 SPEC 被自动晋升（按分流进入 ready 或 reviewing）；若进入 reviewing 则派发评审
  run；进入 ready 后不派发实现 run，直到人工激活

#### Scenario: full 档下 manual 哨兵停留草稿
- **WHEN** `start_after_scope` 为 `full`，SPEC 为 `drafted` 且 `start_after` 为 `manual`
- **THEN** 该 SPEC 停留 `drafted`（不晋升、不评审、不实现），直到人工激活

### Requirement: scope 不影响实现派发口

`gates.start_after_scope` MUST NOT 改变实现派发口的 `start_after` 行为：`ready` 态 SPEC 的
派发筛选（`_on_spec_ready`、派发队列候选筛选）与恢复派发（`_recover_ready`）对未到期/哨兵
SPEC MUST 恒跳过，与 scope 取值无关。scope 只控制「是否需要提前晋升/评审」，不控制
「是否到点才实现」——后者是 `start_after` 的无条件本职语义。

#### Scenario: full 档下 ready 派发仍受门约束
- **WHEN** `start_after_scope` 为 `full`，SPEC 为 `ready` 且 `start_after` 为未来时间
- **THEN** 该 SPEC 不被派发实现，行为与 `dispatch` 档及未引入该键时一致

#### Scenario: dispatch 档下 ready 派发仍受门约束
- **WHEN** `start_after_scope` 为 `dispatch`，SPEC 为 `ready` 且 `start_after` 未到期
- **THEN** 该 SPEC 不被派发实现

### Requirement: 文档更新

`docs/help/06-governance.md`（定时拾取小节）SHALL 补充 `gates.start_after_scope` 两档语义与
缺省值说明；`docs/help/09-config.md` 的 `gates.*` 键表 SHALL 新增该键一行（取值、缺省、
一句话说明）。

#### Scenario: 文档与实现一致
- **WHEN** 实现合入后查阅两份文档
- **THEN** 均描述了两档语义、缺省 `dispatch`，且与 getter 的缺省一致
