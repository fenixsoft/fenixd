## ADDED Requirements

### Requirement: todo 追加写路径写后即时入库

append_todo_line（core/knowledge_backfill.py）对项目 .fenix/todo.md 发生实际追加后，框架 MUST 在该写路径内完成一次路径限定的就地 git 提交（git add 与 git commit 均以 .fenix/todo.md 为 pathspec）并尝试 push，使 ADR-060 的写入点即时提交原则覆盖全部追加调用方，主树不残留该文件诱发的 merge-back 重叠阻塞。

#### Scenario: 实际追加产生单提交

- **WHEN** tracked 的 .fenix/todo.md 经任一调用方（含 core/knowledge.py:627 蒸馏失败重试登记、core/knowledge_audit.py:1533 转写失败登记）实际追加一行
- **THEN** 产生恰一个包含 .fenix/todo.md 的提交，提交仅含该文件（pathspec 限定），提交后该文件无未提交改动，且不卷入索引中并发暂存的其他内容

#### Scenario: 幂等去重命中不产生提交

- **WHEN** 待追加行已存在、本次调用未发生实际写入
- **THEN** 不产生任何 git 提交

#### Scenario: untracked 或无 git 降级

- **WHEN** .fenix/todo.md 未被 git 跟踪（含所在目录非 git 仓库）
- **THEN** 写入行为与现状一致，不产生提交、不报错

#### Scenario: 提交或 push 失败降级

- **WHEN** git 提交因 index.lock 竞争等原因失败，或提交后 push 失败
- **THEN** 追加写入不回滚、不向调用方抛错，失败经既有日志通道留痕（push 失败降级不重试，本地提交不受影响）

### Requirement: 提交动作在文件锁外执行

就地提交的 git 子命令 MUST 在 .fenix/todo.md 的 flock 释放后执行，MUST NOT 拉长持锁窗口阻塞 code_fix、self_review 等并发追加方。

#### Scenario: 并发追加不被提交动作阻塞

- **WHEN** 一方在提交 todo.md 期间另一方并发调用 append_todo_line
- **THEN** 后者仅需等待文件锁本身，不因前者的 git 子进程而额外阻塞