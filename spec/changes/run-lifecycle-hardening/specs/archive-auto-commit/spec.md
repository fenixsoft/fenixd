# archive-auto-commit

## ADDED Requirements

### Requirement: 归档移动随 push 自动提交

daemon 在 spec done 的 push 流程（main-first）完成代码推送后，MUST 检查主树是否存在 `openspec/changes/` 下的归档移动残留（被归档 spec 目录的删除 + `openspec/changes/archive/` 下未跟踪/已修改的新增文件）；存在时 MUST 以独立提交收口（提交信息格式 `[fenix] archive: <spec-name> 等归档入库`），并在代码 push 之后追加 push。不存在残留时 MUST 零动作（无空提交、无多余 push）。

#### Scenario: 归档残留存在时自动提交

- **WHEN** 某 spec 走完 done → push 流程，主树存在该 spec（或更早 spec）的归档移动残留（`git status` 含 `openspec/changes/<spec>/` 删除项与 `openspec/changes/archive/...` 未跟踪项）
- **THEN** daemon 生成且仅生成一个包含全部归档移动的 commit 并 push 成功，随后 `git status` 对 `openspec/` 路径干净

#### Scenario: 无残留时零动作

- **WHEN** push 流程尾部主树对 `openspec/changes/` 无任何归档移动残留
- **THEN** 不产生 commit、不产生 push 动作，日志无归档提交记录

#### Scenario: 提交失败不阻塞主流程

- **WHEN** 归档提交因 git 冲突或 hook 拒绝而失败
- **THEN** daemon 记录 WARNING 级日志并继续既有流程（spec 保持 done/pushed 终态），残留留给下一次 push 流程重试；不得将 spec 打回或置 blocked

### Requirement: 归档提交内容限定

归档提交 MUST 只包含 `openspec/changes/` 路径下的变更（删除项 + archive 新增项），MUST NOT 携带工作区其他未提交改动（如源码、STATE.md 运行时文件）。

#### Scenario: 不夹带无关改动

- **WHEN** 主树同时存在源码修改（非 openspec 路径）与归档残留，归档自动提交执行
- **THEN** 生成的 commit 的 diff 仅含 `openspec/changes/` 路径，源码修改仍留在工作区
