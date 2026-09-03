## ADDED Requirements

### Requirement: 原生 change 归档命令

系统 SHALL 提供 `bin/fenix_archive.py <name>`：将 `openspec/changes/<name>/` 移动到 `openspec/changes/archive/YYYY-MM-DD-<name>`（YYYY-MM-DD 为当天日期）。目标已存在时 SHALL 返回错误并提示改名或换日期，不得覆盖。

#### Scenario: 归档完成的 change

- **WHEN** 对存在的 change 运行 `bin/fenix_archive.py add-user-login`
- **THEN** 目录移动至 `openspec/changes/archive/YYYY-MM-DD-add-user-login`，输出 JSON 含 `ok` 与移动前后路径

#### Scenario: 目标已存在报错不覆盖

- **WHEN** `openspec/changes/archive/YYYY-MM-DD-add-user-login` 已存在时再次归档同名 change
- **THEN** 返回错误并提示改名或换日期，原目录不被覆盖

#### Scenario: 不存在的 change 报错

- **WHEN** 对 `openspec/changes/` 下不存在的名称运行归档
- **THEN** 返回错误，提示该 change 不存在

### Requirement: fenix-archive skill

系统 SHALL 提供 `fenix-archive` skill：列出 `openspec/changes/` 下未归档的 change，由用户选择后调用 `bin/fenix_archive.py` 执行归档并展示结果。

#### Scenario: 选择并归档

- **WHEN** 用户通过 fenix-archive 选择某未归档 change 并确认
- **THEN** skill 调用 `bin/fenix_archive.py <name>` 完成归档并展示归档路径

#### Scenario: 未完成任务仅提示不阻塞

- **WHEN** 所选 change 的 tasks.md 尚有未完成勾选
- **THEN** skill 提示未完成任务数，用户确认后仍执行归档
