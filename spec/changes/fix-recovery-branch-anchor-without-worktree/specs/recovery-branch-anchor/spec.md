# spec-recovery-branch-anchor

## ADDED Requirements

### Requirement: 实现产物成功即落锚点

implement / repair run 到达**终态成功**时，框架 MUST 在 merge-back（含 repair 的 re-merge-back）**之前**把该 run 的 `branch` 与 `implementer_run` 写入 STATE。MUST NOT 仅在 merge-back 成功后才写——该时机使「已实现、未合并」这一段在飞状态在 STATE 中无任何分支锚点。

`branch` 字段的语义为「**本轮实现分支**」（写入时机提前，取值集合不变）。run 未达终态成功（失败、中断、被杀）时 MUST NOT 写入，保持既有语义。

写入点 MUST 定序在**全部 merge 前置闸门之后**：零变更哨（`core/pm_engine/dispatch.py:770`）、交付物守卫与缺件异议（`:844-900`）、tasks.md 收口复检（`:904`）均以 `status: ready/blocked` 早退并进入下一轮全新派发，且均在 merge 预演（`:945`）之前（零变更哨内的「确认型 no-op 放行」`:780-793` 除外：它直转 `implemented`，属终态成功）。MUST NOT 在这些早退路径上留下**本轮**锚点——本轮已放弃、下一轮另建分支，而解析链第一层（STATE.`branch`）优先于第二层（在册 worktree），下一轮在飞期间重启即命中已放弃的本轮分支并整轮续做，恰是本 SPEC 要消除的「丢一轮」形态。实现口径二选一：锚点写入紧邻 merge 预演之前（早退之后）；或保留早退之前的写入点，但在上述早退分支内一并清锚点。

#### Scenario: 早退路径不残留本轮锚点

- **WHEN** implementer run 到达终态 success 落锚点**之前**先命中零变更哨（`dispatch.py:770`）、交付物守卫缺件异议（`844-900`）或 tasks.md 收口复检（`904`）并以 `status: ready/blocked` 早退
- **THEN** 该轮结束（下一轮另建分支）后 STATE MUST NOT 残留本轮的 `branch`/`implementer_run`，使下一轮在飞期间重启时解析链第一层仍会命中它

#### Scenario: implementer 成功即落盘，不等 merge-back

- **WHEN** implementer run 返回终态 success，随即 merge 预演检出语义冲突并直通 repair 通道
- **THEN** 进入 repair 之前 STATE 的 `branch` 已等于该 run 的实现分支，`implementer_run` 已等于该 run_id

#### Scenario: repair 成功即落盘，不等 re-merge-back

- **WHEN** repair run 返回终态 success，随后 re-merge-back 尚未执行
- **THEN** STATE 的 `branch` 已等于被修复的实现分支

#### Scenario: 失败 run 不写锚点

- **WHEN** implementer run 以 error 或非正常退出结束
- **THEN** STATE 的 `branch` 不被该 run 写入（保持原有值或 null）

#### Scenario: 与 merge-back 成功后写入值一致

- **WHEN** 同一 spec 的同一轮实现分别在「run 成功时」与「merge-back 成功后」观察 STATE.branch
- **THEN** 两次取值为同一分支名，MUST NOT 出现取值漂移

### Requirement: 锚点随实现轮次失效

`branch` 锚点只在「该轮实现到本轮收口」这一区间内有效。某 spec 进入**全新实现轮次**（非 `_recovery_resume` 续做的普通派发）时，框架 MUST 先失效上一轮的 `branch` / `implementer_run` 锚点（清空或改写为本轮值）。实现位置 MUST 优先落在**全新实现派发的唯一入口**（`core/pm_engine/dispatch.py:672` 的 `_run_agent_worker` → `elif agent_type == "implementer":` 分支内、`_recovery_resume` 续做判定（`:690-706`）之后、`run_implementer(...)`（`:724`）之前的非续做路径；fast-track 走独立入口 `:643`，纳入本要求时须同样落点），使全部重派出口机械覆盖；MUST NOT 只按 `status: ready` 写点逐点枚举——出口清单以 `grep -n '"status": "ready"' core/pm_engine/dispatch.py` 为审计口径，枚举必然遗漏，且下游每新增一个重派出口即重新引入本缺陷。覆盖范围 MUST 至少含 merge-back 失败降级 ready 重试、repair 熔断后的 fallback 重派，以及不经派发而直接改状态的出口（含人工复位 `blocked`→`ready` 后重派）。

理由：锚点解析链的第一层是 STATE.`branch`，优先于第二层（在册 worktree）。若上一轮锚点残留在 STATE，而该 spec 正在跑新一轮（其 worktree/分支为全新载体），重启恢复会按第一层选中**已放弃的上一轮分支**并重建载体续做，把新一轮在飞的成果整轮晾掉——这是 `interrupt-recovery-preserve` 要消除的「丢一轮」形态，MUST NOT 由锚点提前落盘引入。

#### Scenario: 新轮次派发前失效旧锚点

- **WHEN** 某 spec 第一轮 run 成功并落锚点、merge-back 失败降级 ready，随后被派发全新一轮实现
- **THEN** 新一轮在飞期间 STATE 的 `branch` MUST NOT 仍指向上一轮分支

#### Scenario: 陈旧锚点不压过本轮在册载体

- **WHEN** STATE 残留上一轮 `branch`，同时本轮在册 worktree（承载本轮新分支）在场，此时 daemon 重启
- **THEN** 恢复 MUST 保留本轮分支载体，MUST NOT 仅凭第一层陈旧字段选中上一轮分支并整轮续做

### Requirement: 锚点的 git 分支命名空间回落

恢复链解析某 spec 的分支锚点时，MUST 按以下顺序取值，任一环节命中即停止：

1. STATE 的 `branch` 字段；
2. `worktree_manager` 的 spec → 在册 worktree 事实查询（`git worktree list --porcelain` + worktree 命名约定）；
3. **git 分支命名空间枚举**：按**与分支创建端同源**的前缀枚举 `refs/heads/<prefix>/<spec>-*`（创建端硬编码 `fenix/`，见 `core/worktree_manager.py:223/226`；故 `<prefix>` MUST 取 `fenix/` 或「配置 `worktree.implement_branch_prefix` ∪ `fenix/`」并集，MUST NOT 仅凭配置值取前缀——非 `fenix` 配置下创建端仍产出 `fenix/<spec>-<ts>`，仅按配置枚举会扫空命名空间、本层静默失效），候选排序规则为——先取 `main` 为其祖先者（`git merge-base --is-ancestor main <branch>` 成立，即已含 main 的合并），在此基础上取 committerdate 最新者；无「已含合并」候选时取 `git rev-list --count main..<branch>` 最大者。

命名空间枚举 MUST NOT 依赖内存表（`_active_worktrees` / `_wt_branches`），MUST NOT 因 worktree 已被清理而放弃该回落——枚举的事实源是 git refs，与 worktree 是否在册无关。

候选清单 MUST 按「**完整 spec 名 + 分隔符边界**」全等比较生成，MUST NOT 把 `<prefix>/<spec>-*` 的前缀 glob 命中集合直接当候选：spec 名可互为前缀（如 `fix-x` 与 `fix-x-y`），glob 会把 `fix-x-y` 的实现分支算作 `fix-x` 的候选，导致跨 spec 误配（本项目已有实测先例）。口径 MUST 与 `worktree_manager._wt_name_matches_spec`（`core/worktree_manager.py:3201-3217`）及 `engine.py:1869-1871` 的既有边界守卫一致：分支名去掉 `<prefix>/` 后按最后一个 `-` 分段，末段 MUST 为纯数字时间戳、其前段 MUST 与该 spec 名全等；不满足者 MUST NOT 进入候选清单。`<prefix>/verify-<spec>-*` 形态的验证分支不是实现分支，MUST NOT 进入候选清单。

第三层候选 MUST 与第一/二层同口径过既有的「`main..branch` 非空」闸门：`main..branch` 为空的候选等价于分支 tip 与 main 同点（零提交分支），MUST NOT 被当作可保留锚点，MUST 走零提交清空重建路径（与 `interrupt-recovery-preserve` 的「零提交分支走现行清空」一致）。该闸门 MUST **先于排序**应用于候选集——零提交候选 MUST 自候选清单中剔除、不得参与排序，否则一个 tip 与 main 同点（`main` 恰为其祖先）且 committerdate 最新的分支可能被排序选中后又过不了闸门，使本可保留的其它候选被误判为不可得。注意「main 为分支祖先」本身不构成「已含未合并成果」——repair 已把 main 合入分支的形态必然 `main..branch` 非空（冲突解决提交落在分支上），故排序规则中的首取项不改变该闸门。

命中多个候选且无法按上述规则唯一确定时，MUST 取排序规则下的最优者并打 WARNING 列出全部候选；MUST NOT 静默取首个。

#### Scenario: worktree 已清但分支已合并 main

- **WHEN** 某 implementing spec 的 STATE.branch 为 null、无在册 worktree，但其分支 `<prefix>/<spec>-<旧ts>` 存在、`main` 是其祖先、且该分支自带未合并提交（`git rev-list --count main..<branch>` ≥ 1，即 repair 已把 main 合入分支并留下冲突解决提交）
- **THEN** 回落命中该分支，恢复按保留续做路径命中并保留该 branch

#### Scenario: 分支尚未合并 main

- **WHEN** 某 implementing spec 的 STATE.branch 为 null、无在册 worktree，其分支存在但 `main..branch` 非空
- **THEN** 回落命中该分支，恢复保留该 branch 并按 resume 续做

#### Scenario: 多候选优先取「已含 main 合并」者并留痕

- **WHEN** 同一 spec 存在多个 `<prefix>/<spec>-*` 分支、均相对 main 有未合并提交，其中部分候选已含 main 的合并（`main` 为其祖先）
- **THEN** MUST 取「已含 main 合并」候选中 committerdate 最新者（首取项优先于 ahead 计数项，即使其它候选的 `rev-list --count` 更大），并打 WARNING 列出全部候选分支名

#### Scenario: 无「已含 main 合并」候选时按 ahead 取最大

- **WHEN** 多个候选均未含 main 的合并（`main` 不是其中任何一个的祖先）且均相对 main 有未合并提交
- **THEN** 取 `git rev-list --count main..<branch>` 最大者，并打 WARNING 列出全部候选分支名

#### Scenario: 枚举前缀与分支创建端同源

- **WHEN** 分支由创建端产出于 `fenix/<spec>-<ts>`（创建端硬编码 `fenix/`），而配置 `worktree.implement_branch_prefix` 被设为非 `fenix` 的值
- **THEN** 命名空间枚举 MUST 仍按创建端口径命中该 `fenix/<spec>-<ts>` 分支（或取「配置值 ∪ `fenix/`」并集），MUST NOT 仅用配置值构造匹配模式而扫空命名空间、把该 spec 判为「锚点不可得」

#### Scenario: spec 名互为前缀不跨 spec 误配

- **WHEN** 存在两个具前缀关系的 spec（如 `fix-x` 与 `fix-x-y`），解析 `fix-x` 的锚点时命名空间中同时存在属于两者的分支（`<prefix>/fix-x-<ts>` 与 `<prefix>/fix-x-y-<ts>`），且后者相对 main 的提交更多
- **THEN** 候选清单 MUST 仅含 `<prefix>/fix-x-<ts>`，`<prefix>/fix-x-y-<ts>` MUST NOT 进入候选，MUST NOT 因前缀 glob 命中而被当作 `fix-x` 的锚点

#### Scenario: 零提交候选不参与排序

- **WHEN** 命名空间中同时存在「tip 与 main 同点（`main..branch` 为空）且 committerdate 最新」的候选与「相对 main 有未合并提交」的候选
- **THEN** 零提交候选 MUST 自候选清单剔除、不参与排序，锚点取后者；MUST NOT 因前者在排序中胜出又过不了闸门而把整个 spec 判为「锚点不可得」

#### Scenario: 无候选时不误判

- **WHEN** 命名空间枚举无任何 `<prefix>/<spec>-*` 命中，或全部候选相对 main 零提交（含分支 tip 与 main 同点的零提交分支——`main..branch` 为空，MUST NOT 因「main 是其祖先」而被判为可保留锚点）
- **THEN** 锚点判定为不可得，走既有清空重建兼容路径（与 `interrupt-recovery-preserve` 的「零提交分支走现行清空」一致）

### Requirement: 锚点不可得的强制留痕

恢复链在「无任何锚点」而走清空重建路径时，MUST 打 WARNING，内容含 spec 名与命名空间枚举的命中结果（候选分支名清单，无命中则显式标注为空）。MUST NOT 以无日志的早退结束该判定——锚点缺失是重大恢复语义事件，必须有可检索的留痕。

#### Scenario: 无锚点清空重建时留痕

- **WHEN** 某 implementing spec 在 STATE.branch、在册 worktree、分支命名空间三处均无锚点
- **THEN** 日志出现 WARNING，含该 spec 名与「分支命名空间枚举：无候选」的显式结论

#### Scenario: 锚点存在但载体不可用

- **WHEN** 锚点已解析出分支名但 `is_available` 三态判定不可用
- **THEN** 在既有降级 WARNING 中一并打出该分支名与降级原因，不额外引入无锚点结论
