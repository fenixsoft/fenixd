# spec-doc-view Spec（delta）

## MODIFIED Requirements

### Requirement: 读取 SPEC 文档内容

系统 SHALL 提供 `GET /api/spec-doc?project=<name>&spec=<name>&doc=<proposal|design|tasks>` 端点，按项目与 SPEC 名称读取 `spec/changes/<spec>/` 目录下的 `proposal.md`、`design.md` 或 `tasks.md` 原文，返回 `{found: boolean, content: string}`。`doc` 参数由原 `{proposal, design}` 白名单扩展为 `{proposal, design, tasks}`——`tasks.md` 与 `proposal.md` 同目录，读取路径构造、文件缺失空态语义与既有行为一致，其余值 SHALL 返回 400。`spec` 名称 SHALL 匹配 kebab-case（`^[a-z0-9][a-z0-9-]*$`）；不匹配或该 SPEC 不存在于项目中 SHALL 返回 404，且 SHALL 不读取任何 `spec/changes/` 目录之外的文件。该端点 SHALL 不影响既有 `/api/specs` 及其它端点。

#### Scenario: 读取存在的任务文档
- **WHEN** 请求 `GET /api/spec-doc?project=demo&spec=add-user-login&doc=tasks`
- **THEN** 返回 200，`found` 为 `true`，`content` 等于 `spec/changes/add-user-login/tasks.md` 的文件原文

#### Scenario: 任务文档缺失返回空态语义
- **WHEN** `spec/changes/<spec>/tasks.md` 文件不存在，请求 `doc=tasks`
- **THEN** 返回 200，`found` 为 `false`，`content` 为空字符串

#### Scenario: 既有 doc 行为不回归
- **WHEN** 请求 `doc=proposal` 或 `doc=design`（文件存在与缺失、`doc=readme` 400、非法或未知 SPEC 404 各分支）
- **THEN** 行为与扩展前完全一致（读取原文、空态语义、400/404 校验不变）