## MODIFIED Requirements

### Requirement: 原生 change 归档命令

系统 SHALL 提供 `bin/fenix_archive.py <name>`：将 `spec/changes/<name>/` 移动到 `spec/archive/YYYY-MM-DD-<name>`（YYYY-MM-DD 为当天日期）。目录移动成功后，若 STATE.md 存在该 change 的条目，系统 SHALL 迁出该条目至归档清单 `.fenix/STATE.archive.md`（`archived_by=cli`；迁出失败降级为输出中的告警字段，目录移动不回滚）。目标已存在时 SHALL 返回错误并提示改名或换日期，不得覆盖。

#### Scenario: 归档完成的 change

- **WHEN** 对存在的 change 运行 `bin/fenix_archive.py add-user-login`
- **THEN** 目录移动至 `spec/archive/YYYY-MM-DD-add-user-login`，STATE.md 中该条目迁出至清单（含 archived_at 与 archived_by=cli），输出 JSON 含 `ok` 与移动前后路径

#### Scenario: STATE 无条目仍可归档

- **WHEN** 对 STATE.md 无条目的 change（如手工创建目录）运行归档
- **THEN** 目录正常归档，输出含迁出未找到的说明性信息，不报错

#### Scenario: 目标已存在报错不覆盖

- **WHEN** `spec/archive/YYYY-MM-DD-add-user-login` 已存在时再次归档同名 change
- **THEN** 返回错误并提示改名或换日期，原目录与 STATE.md 条目均不变

#### Scenario: 不存在的 change 报错

- **WHEN** 对 `spec/changes/` 下不存在的名称运行归档
- **THEN** 返回错误，提示该 change 不存在

### Requirement: fenix-archive skill

系统 SHALL 提供 `fenix-archive` skill：列出 `spec/changes/` 下未归档的 change，由用户选择后调用 `bin/fenix_archive.py` 执行归档并展示结果（含条目已迁出 STATE.md 的反馈）。

#### Scenario: 选择并归档

- **WHEN** 用户通过 fenix-archive 选择某未归档 change 并确认
- **THEN** skill 调用 `bin/fenix_archive.py <name>` 完成归档，条目迁出清单，展示归档路径与迁出结果

#### Scenario: 未完成任务仅提示不阻塞

- **WHEN** 所选 change 的 tasks.md 尚有未完成勾选
- **THEN** skill 提示未完成任务数，用户确认后仍执行归档
