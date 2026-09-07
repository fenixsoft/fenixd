## ADDED Requirements

### Requirement: 归档 SPEC 的文档与任务清单仍可读

已归档 SPEC（STATE.md 条目保留、`spec/changes/<name>/` 已移入 `spec/archive/`）SHALL 仍可被 dashboard 读侧访问：`/api/spec-doc` 对该 SPEC 的五类文档（proposal/design/tasks/verification/scenarios）SHALL 从其归档目录读取并返回原文（found=true）；`/api/specs/<spec>` 详情的任务清单（tasks/tasks_note）SHALL 从归档目录的 tasks.md 解析。归档目录命名解析 SHALL 与归档写侧规则一致（`YYYY-MM-DD-<name>`，含冲突时追加的数字后缀）；同名 SPEC 存在多个归档目录时 SHALL 取名称排序最大（最新）的一份。活跃 SPEC（目录仍在 `spec/changes/<name>/`）SHALL 完全维持现有行为，不受回退逻辑影响。

#### Scenario: 已归档 SPEC 文档页签可读

- **GIVEN** 某 SPEC 已归档，`spec/archive/2026-09-02-add-demo/proposal.md` 存在且 STATE.md 条目保留
- **WHEN** 在已归档视图中打开该 SPEC 的 proposal 文档页签
- **THEN** API 返回 found=true 且内容与归档目录中文件原文一致；design/tasks 页签同理

#### Scenario: 已归档 SPEC 验证报告与场景清单可读

- **GIVEN** 某 SPEC 已归档，归档目录含 verification-report.md 与 specs/&lt;capability&gt;/spec.md
- **WHEN** 请求其 verification 与 scenarios 文档
- **THEN** verification 返回归档目录中报告原文；scenarios 返回归档 specs 目录的场景清单汇总

#### Scenario: 已归档 SPEC 任务清单可读

- **GIVEN** 某 SPEC 已归档，归档目录含 tasks.md（含已完成勾选项）
- **WHEN** 打开该 SPEC 详情页
- **THEN** 任务卡片按归档目录 tasks.md 渲染（含完成状态），不显示为空态

#### Scenario: 活跃 SPEC 行为不变

- **GIVEN** 某 SPEC 目录仍在 spec/changes/&lt;name&gt;/
- **WHEN** 请求其任意文档与任务清单
- **THEN** 读取活跃目录，结果与回退逻辑引入前一致

#### Scenario: 归档路径防穿越保持

- **WHEN** 以含路径穿越片段（如 `..%2F`）的 spec 参数请求 spec-doc
- **THEN** 请求被拒绝（400/404 语义），任何文件内容不返回——回退解析不得引入穿越可能

#### Scenario: 多个同名归档目录取最新

- **GIVEN** spec/archive/ 下同时存在 2026-09-01-add-demo 与 2026-09-05-add-demo 两个归档目录
- **WHEN** 请求 add-demo 的文档
- **THEN** 返回 2026-09-05-add-demo（名称排序最大）中的内容
