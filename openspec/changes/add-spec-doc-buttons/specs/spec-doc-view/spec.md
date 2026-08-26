## ADDED Requirements

### Requirement: 读取 SPEC 文档内容

系统 SHALL 提供 `GET /api/spec-doc?project=<name>&spec=<name>&doc=<proposal|design>` 端点，按项目与 SPEC 名称读取 `openspec/changes/<spec>/` 目录下的 `proposal.md` 或 `design.md` 原文，返回 `{found: boolean, content: string}`。`doc` 参数仅接受 `proposal` 与 `design` 两个值，其余值 SHALL 返回 400。`spec` 名称 SHALL 匹配 kebab-case（`^[a-z0-9][a-z0-9-]*$`）；不匹配或该 SPEC 不存在于项目中 SHALL 返回 404，且 SHALL 不读取任何 `openspec/changes/` 目录之外的文件。该端点 SHALL 不影响既有 `/api/specs` 及其它端点。

#### Scenario: 读取存在的文档
- **WHEN** 请求 `GET /api/spec-doc?project=demo&spec=add-user-login&doc=proposal`
- **THEN** 返回 200，`found` 为 `true`，`content` 等于 `openspec/changes/add-user-login/proposal.md` 的文件原文

#### Scenario: 文档缺失返回空态语义
- **WHEN** `openspec/changes/<spec>/design.md` 文件不存在，请求 `doc=design`
- **THEN** 返回 200，`found` 为 `false`，`content` 为空字符串

#### Scenario: 非法 doc 参数
- **WHEN** 请求 `doc=readme` 或 `doc` 缺失
- **THEN** 返回 400

#### Scenario: 非法或未知 SPEC 名称
- **WHEN** 请求 `spec=../../etc/passwd`、`spec` 含大写字母，或该 SPEC 不在项目 STATE.md 中
- **THEN** 返回 404，且不读取 `openspec/changes/` 之外的任何文件