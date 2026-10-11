## ADDED Requirements

### Requirement: 自进化标记写后即时入库

自进化裁决标记写入 tracked 的 .fenix/todo.md 后，框架 MUST 在写路径内完成该文件的 git 提交，使主树不残留该文件的未提交改动。

#### Scenario: tracked 项目写入后产生单提交

- **WHEN** 项目 .fenix/todo.md 被 git 跟踪且一轮标记写入完成
- **THEN** 该项目产生恰一个包含 .fenix/todo.md 的提交（同轮同项目多条目合并；一轮涉及多个项目时按项目各一次），提交仅含该文件（commit 带 pathspec 限定），提交后 git status 对该文件无未提交改动

#### Scenario: untracked 项目跳过提交

- **WHEN** 项目 .fenix/todo.md 未被 git 跟踪（含目录非 git 仓库）
- **THEN** 写入行为与现状一致，不产生提交、不报错

#### Scenario: 提交失败降级

- **WHEN** git 提交因 index.lock 竞争等原因失败，或提交后的 push 失败
- **THEN** 标记写入不回滚、不向调用方抛错，失败经既有日志通道留痕（commit 失败待下一次写入再尝试，push 失败降级不重试），本地提交不受 push 失败影响