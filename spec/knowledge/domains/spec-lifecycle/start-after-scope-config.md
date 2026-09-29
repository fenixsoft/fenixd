# start_after 门控覆盖范围配置（scope 两档）
<!-- knowledge: capability=start-after-scope-config rev=1
     sources=spec/archive/2026-09-24-add-start-after-scope-config -->

声明 `start_after` 未到期（含哨兵 manual）的 SPEC 除实现派发外，是否同时被按住晋升与评审入口。

## 规则

- 配置键 `gates.start_after_scope`，枚举 `full` / `dispatch`，缺省 `dispatch`；配置校验拒绝非枚举值并在加载时报错，错误信息指出合法取值；纳入 Dashboard 受管配置键白名单，支持设置页「审批」页签读写、用户级→项目级同步与配置热更新（30s mtime 原地重载），无需重启 daemon。
- `dispatch`（缺省）：`start_after` 只约束实现派发链——`drafted` SPEC 照常被自动晋升（直通 `ready` 或按方案评审分流 `drafted → reviewing`），方案评审立即进行；实现派发等到期/激活。
- `full`：`start_after` 同时约束晋升入口、评审入口与对应恢复分支——SPEC 停留 `drafted`，直到到期/激活才晋升并起评审。
- scope 作用于 `start_after` 取值域**全部阻塞态**：具体未来时间与哨兵 `manual` 一律按当前 scope 决定是否按住晋升/评审入口，不得只对定时值生效而让哨兵恒定按住晋升。
- `manual` 哨兵在 `dispatch` 档下的语义：SPEC 立即晋升并（按评审判定）起评审，评审通过后停在 `ready`，由实现派发口的无条件 `start_after` 门拦住不实现，直到人工激活（`start_after` 置 null）——「哨兵不自动实现」的保证恒成立，变的只是「是否提前跑评审」。`full` 档下哨兵 SPEC 停留 `drafted`（不晋升、不评审、不实现），直到人工激活。
- scope 不影响实现派发口：`ready` 态 SPEC 的派发筛选（`_on_spec_ready`、派发队列候选筛选）与恢复派发（`_recover_ready`）对未到期/哨兵 SPEC 恒跳过，与 scope 取值无关——scope 只控制「是否需要提前晋升/评审」，不控制「是否到点才实现」（后者是 `start_after` 的无条件本职语义）。
- 文档同步：治理文档（docs/help/06-governance.md）定时拾取小节描述两档语义与缺省值；配置文档（docs/help/09-config.md）的 `gates.*` 键表登记该键（取值、缺省、一句话说明），与 getter 缺省一致。

## 溯源

- [2026-09-24 2026-09-24-add-start-after-scope-config](spec/archive/2026-09-24-add-start-after-scope-config/) — 新增 scope 配置键：dispatch/full 两档语义、作用于定时值与哨兵全阻塞态、实现派发口不受 scope 影响、文档同步
