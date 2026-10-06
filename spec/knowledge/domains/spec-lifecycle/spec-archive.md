# SPEC 归档（手动归档命令与 skill）
<!-- knowledge: capability=spec-archive rev=2
     sources=spec/archive/2026-09-02-integrate-openspec-native,spec/archive/2026-10-06-add-archive-state-migration -->

把完成的 change 从 `spec/changes/` 移入 `spec/archive/`：一条 CLI 命令 + 一个选择式 skill。

## 规则

- 目录移动成功后，若 STATE.md 存在该 change 条目则迁出至归档清单 `.fenix/STATE.archive.md`（`archived_by=cli`，含 `archived_at` 溯源）；迁出失败降级为输出中的告警字段，目录移动不回滚。STATE.md 无条目（如手工创建目录的 change）仍可归档，输出含迁出未找到的说明性信息，不报错。
- 目标归档目录已存在时返回错误并提示改名或换日期，不得覆盖（原目录与 STATE.md 条目均不变）；对 `spec/changes/` 下不存在的名称返回错误并提示该 change 不存在。
- `fenix-archive` skill：列出 `spec/changes/` 下未归档的 change，由用户选择后调用 `bin/fenix_archive.py <name>` 执行归档并展示结果（归档路径与条目迁出结果）。
- 所选 change 的 tasks.md 尚有未完成勾选时，skill 仅提示未完成任务数，不阻塞归档；用户确认后仍执行。

## 溯源

- 2026-09-02 integrate-openspec-native（spec/archive/2026-09-02-integrate-openspec-native） — 新增原生归档命令与 fenix-archive skill：目录移动与防覆盖、未完成任务提示不阻塞
- 2026-10-06 add-archive-state-migration（spec/archive/2026-10-06-add-archive-state-migration） — 归档成功后迁出 STATE.md 条目至归档清单（archived_by=cli，失败降级告警不回滚目录移动）；STATE 无条目仍可归档并输出说明性信息
