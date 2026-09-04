# tasks-md-tracking 能力规格

## ADDED Requirements

### Requirement: tasks.md 分组标题格式契约（写入端）

`fenix_spec.py` 的 tasks artifact 生成指引（`instructions` 返回的 `instruction` 与 `template` 字段文本）SHALL 将分组标题格式定义为 MUST 约定：`## <编号>. <标题>`——编号为阿拉伯数字、编号后必须带点号（如 `## 1. 归档自动提交`）。指引文本 SHALL 同时说明：下游解析器（CLI 进展脚本与 dashboard）与晋升 lint 均依赖该格式，偏离将导致任务清单不可跟踪。

#### Scenario: 生成指引包含格式 MUST 约定

- **WHEN** 调用 `fenix_spec.py instructions tasks --change <任意 change>`
- **THEN** 返回的 `instruction` 文本包含分组标题 MUST 约定（含「编号 + 点号」字样与正确示例 `## 1.`），`template` 字段的分组标题示例均为 `## <数字>. ` 形态

#### Scenario: 存量双格式解析兼容不受写入端影响

- **WHEN** 对既有 spec（分组标题为 `## 1. 标题` 或 `## 1 标题` 两种历史格式）执行 CLI 进展脚本与 dashboard `parse_tasks`
- **THEN** 两种格式均能解析出任务分组（点号可选兼容保留），run-lifecycle-hardening 显示 17/17

### Requirement: tasks.md 可解析性晋升拦截

drafted→ready 晋升校验 SHALL 新增 tasks.md 可解析性 lint：`openspec/changes/<spec>/tasks.md` 文件存在、但以与下游解析同源的正则规则解析出 0 个任务分组时，判定为 lint 违规——SPEC 保持 `drafted` 状态并在 STATE.md 写入 error，错误消息 SHALL 含「tasks.md」字样；解析出 ≥1 个分组（含点号可选双格式）时不拦截。lint 自身异常时 SHALL fail-open 放行晋升（与既有 Deliverables 声明 lint 同语义）。

#### Scenario: 不可解析的 tasks.md 被拒绝晋升

- **GIVEN** 某 drafted SPEC 的 tasks.md 存在但分组标题无编号（如 `## 事项`），按下游解析规则解析出 0 个任务分组
- **WHEN** 触发 drafted→ready 晋升
- **THEN** SPEC 状态保持 `drafted`，STATE.md 该 spec 的 error 字段含「tasks.md」，不发生 implementer 派发
- **AND** 修正分组标题为可解析格式后重新触发晋升，晋升成功

#### Scenario: 双历史格式不误拦存量 spec

- **WHEN** 对任务分组标题分别为 `## 1. 标题` 与 `## 1 标题` 的两个 drafted SPEC 触发晋升 lint
- **THEN** 两者均解析出 ≥1 分组，晋升不被拦截、无 error 写入

#### Scenario: lint 异常 fail-open 放行

- **WHEN** 可解析性 lint 执行中抛出异常（如文件读取失败）
- **THEN** 晋升不被阻塞（fail-open），异常记 WARNING 日志

### Requirement: 解析失败显式提示（CLI 与 dashboard 不再静默）

`fenix_process.py` 与 dashboard 对「tasks.md 存在但解析出 0 分组」SHALL 给出显式提示，与「无 tasks.md 文件」和「正常解析」两种情况在输出上可区分：

- CLI 进展脚本：tasks.md 存在但分组解析为空时，SHALL 打印包含「tasks.md」与「未解析出任务」字样的警告行（warning 视觉样式）；无 tasks.md 时维持现状（不打印任务区块、不打印警告）。
- dashboard 后端：SPEC 详情数据 SHALL 新增 `tasks_note` 字段——tasks.md 存在但 `parse_tasks` 返回空列表时为非空提示文本（含「未解析出任务」字样），否则为 `None`。
- dashboard 前端（v3 spec 详情页任务清单 Card）：`tasks_note` 非空时 SHALL 显示 warning 级提示文本；无 tasks.md 时维持「暂无任务清单」secondary 空态。

#### Scenario: CLI 对不可解析 tasks.md 打印警告

- **GIVEN** 某 SPEC 的 tasks.md 存在但解析出 0 个任务分组
- **WHEN** 运行 `python3 .fenix/bin/fenix_process.py <spec-name>`
- **THEN** 输出包含警告行，内容含「tasks.md」与「未解析出任务」字样，其余区块（时间线/验证进度）正常输出

#### Scenario: CLI 正常与无文件两种情况不受影响

- **WHEN** 分别对「tasks.md 可正常解析」与「无 tasks.md 文件」的 SPEC 运行 CLI 进展脚本
- **THEN** 前者打印任务清单区块且无警告行；后者既无任务区块也无警告行

#### Scenario: dashboard 详情页区分三种空态

- **GIVEN** fixture 项目中三个 SPEC：A 解析出任务分组、B tasks.md 存在但 0 分组、C 无 tasks.md
- **WHEN** 请求三者的 SPEC 详情并渲染 v3 详情页
- **THEN** A 显示任务清单且无提示；B 的任务清单 Card 显示 warning 提示（`tasks_note` 非空，含「未解析出任务」字样）；C 显示 secondary「暂无任务清单」
