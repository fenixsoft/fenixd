# SPEC 归档（手动归档命令与 skill）
<!-- knowledge: capability=spec-archive rev=1
     sources=spec/archive/2026-09-02-integrate-openspec-native -->

把完成的 change 从 `spec/changes/` 移入 `spec/archive/`：一条 CLI 命令 + 一个选择式 skill。

## 规则

- 归档命令 `bin/fenix_archive.py <name>`：将 `spec/changes/<name>/` 移动到 `spec/archive/YYYY-MM-DD-<name>`（YYYY-MM-DD 为当天日期）；输出 JSON 含 `ok` 与移动前后路径。
- 目标目录已存在时返回错误并提示改名或换日期，不得覆盖；对 `spec/changes/` 下不存在的名称返回错误并提示该 change 不存在。
- `fenix-archive` skill：列出 `spec/changes/` 下未归档的 change，由用户选择后调用 `bin/fenix_archive.py <name>` 执行归档并展示归档路径。
- 所选 change 的 tasks.md 尚有未完成勾选时，skill 仅提示未完成任务数，不阻塞归档；用户确认后仍执行。

## 溯源

- 2026-09-02 2026-09-02-integrate-openspec-native — 新增原生归档命令与 fenix-archive skill：目录移动与防覆盖、未完成任务提示不阻塞
