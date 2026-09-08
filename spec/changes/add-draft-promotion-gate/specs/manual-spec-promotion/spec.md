# manual-spec-promotion — SPEC 草稿人工放行通道

## ADDED Requirements

### Requirement: 共享晋升函数
系统 SHALL 提供共享晋升函数，供自动晋升链与全部人工放行通道（Dashboard API、CLI）共用，语义 MUST 一致：晋升前软化不可满足声明（含 dispute 审计留痕）→ 晋升 lint（Deliverables 声明 lint + tasks.md 可解析性 lint）→ 违规则停留 drafted 并把违规合并写入 STATE error（与自动晋升既有 error 语义一致）→ 通过则 transition drafted → ready。函数 MUST 幂等防御：目标 SPEC 不存在或状态非 drafted 时 SHALL 拒绝并返回明确原因。

#### Scenario: 与自动晋升同语义
- **WHEN** 同一份 tasks.md（声明合法）分别经自动晋升与人工晋升处理
- **THEN** 两者最终状态均为 ready，且软化/审计行为一致

#### Scenario: lint 违规拦截
- **WHEN** 对声明段存在违规（如目录型声明、gitignored 路径声明为 new/modify）的 drafted SPEC 执行人工晋升
- **THEN** SPEC 停留 drafted，STATE error 写入违规明细（与自动晋升 lint 失败同格式），晋升函数返回失败与违规列表

#### Scenario: 非 drafted 状态拒绝
- **WHEN** 对状态为 ready 或 done 的 SPEC 执行人工晋升
- **THEN** 晋升被拒绝并返回明确原因，STATE 不发生任何变更

### Requirement: Dashboard 晋升 API 与按钮
Dashboard SHALL 提供 `POST /api/spec-promote?project=<name>&spec=<name>` API，语义为对指定 drafted SPEC 执行共享晋升函数。项目列表页 spec 列表 SHALL 为 drafted 状态的 SPEC 提供「晋升 ready」操作入口（带确认），lint 失败时 SHALL 向用户展示违规反馈。

#### Scenario: 按钮仅对 drafted 可见
- **WHEN** spec 列表中某 SPEC 状态为 drafted
- **THEN** 该行提供「晋升 ready」操作入口；非 drafted 状态的行不提供该入口

#### Scenario: 晋升成功反馈
- **WHEN** 用户在项目页对 drafted SPEC 执行晋升且 lint 通过
- **THEN** API 返回成功，SPEC 状态变为 ready，页面刷新后状态可见

#### Scenario: 晋升被 lint 拦截的反馈
- **WHEN** 用户对声明段违规的 drafted SPEC 执行晋升
- **THEN** API 返回失败与违规摘要，页面提示失败原因；SPEC 停留 drafted 且 STATE error 可见

#### Scenario: 目标不存在
- **WHEN** 对 STATE.md 中不存在的 spec 调用晋升 API
- **THEN** 返回 404

### Requirement: CLI promote 命令
系统 SHALL 提供 CLI 命令 `bin/fenix_cli.py promote <spec> [--project <path>]`（缺省 project 为当前目录），与 Dashboard 晋升 API 调用同一共享晋升函数，执行结果（成功/违规列表/拒绝原因）SHALL 打印到终端并以非零退出码表示失败。

#### Scenario: CLI 晋升成功
- **WHEN** 对声明合法的 drafted SPEC 执行 `python3 bin/fenix_cli.py promote <spec>`
- **THEN** 命令输出晋升成功信息，SPEC 状态变为 ready，退出码为 0

#### Scenario: CLI 晋升被拦截
- **WHEN** 对声明段违规的 drafted SPEC 执行 CLI promote
- **THEN** 命令输出违规明细，SPEC 停留 drafted，退出码非 0

#### Scenario: CLI 指定项目路径
- **WHEN** 在项目根目录之外执行并传 `--project <path>`
- **THEN** 晋升作用于指定项目的 STATE.md

### Requirement: 人工晋升后 daemon 感知派发
CLI 与 Dashboard 进程完成晋升（transition ready 落盘）后，daemon SHALL 通过既有机制感知并派发实现：STATE.md watcher 事件或 full_scan recovery 的 ready 分支（`_recover_ready`）兜底，无需引入新的跨进程请求文件类型。

#### Scenario: 晋升后自动进入实现调度
- **WHEN** 用户经 CLI 或 Dashboard 将 drafted SPEC 晋升为 ready
- **THEN** daemon 感知 ready 状态并调度 implementer（即时经 STATE watcher 事件，或最迟在下一轮 full_scan recovery 兜底派发）

#### Scenario: 闸口关闭不影响已晋升 SPEC
- **WHEN** `gates.auto_promote_draft` 为 `false` 且 SPEC 已被人工晋升为 ready
- **THEN** daemon 对该 ready SPEC 正常派发（闸口只作用于 drafted → ready 晋升，不拦截 ready 之后的调度）
