# deliverable-declaration-resolution — 增量规格（写回层对齐）

## MODIFIED Requirements

### Requirement: 分层解析优先序

声明解析 MUST 按固定优先序分层：**分支 / worktree 版本优先**（实现期真实在测
的那份），在分支/worktree 不可用或不含声明段时回退主树版本。读取分支版本 MUST
以只读方式（如 `git show <branch>:spec/changes/<spec>/tasks.md`）或 worktree
内文件读取，MUST NOT 写主树。

回退 MUST 保持 fail-safe：分支读取失败（非零退出、超时、路径不存在）或解析异常
→ 回退主树；两处均不可用 → 返回空结果（等价「无声明段」，守卫跳过），并审计留痕
说明回退去向。

解析入口返回的 `spec_dir`（改写目标）MUST 用于**读取**与**写入**两个方向时语义一致：
当它要被消费方用于**写入**（重定位 / `typo` 修正 / 软化 / 删除）时，MUST 为**实际
命中（生效）的那一层**——worktree 命中则为 worktree 内 spec 目录；仅命中主树回退
时，`spec_dir` 主树路径 MUST NOT 被用作修正写入落点（修正须改走打回 / 凭据通道，
见 `relocation-writeback-layer`），以免写读错层。

#### Scenario: 分支版本优先

- **GIVEN** 主树 tasks.md 声明 `path: core/old.py`，实现分支 HEAD 的 tasks.md 声明
  `path: core/new.py`
- **WHEN** 收工守卫在实现分支上下文解析声明
- **THEN** 解析结果以分支版本为准（含 `core/new.py`，不含 `core/old.py`）

#### Scenario: 分支读取失败回退主树

- **WHEN** `git show <branch>:...tasks.md` 非零退出或超时
- **THEN** 解析回退主树版本
- **AND** 审计留痕记录回退原因

#### Scenario: 两处均不可用返回空

- **WHEN** 分支与主树均无该 SPEC 的声明段
- **THEN** 返回空结果，消费方按「无声明段」语义处理（守卫跳过，行为退化到守卫上线前）

#### Scenario: 写入落点须为命中层

- **GIVEN** 解析命中分支版本（无 worktree）
- **WHEN** 消费方（裁决）拟以 `spec_dir` 写入修正
- **THEN** MUST NOT 直接以主树 `spec/changes/<spec>/` 作为写入落点
- **AND** 走打回 / 凭据登记通道，使修正落在命中层（分支）

## ADDED Requirements

### Requirement: 写回层来源标注

解析入口返回的结果 MUST 附带 `source`（`worktree` / `branch` / `main`）与 `spec_dir`，
供消费方判定「修正写入落点是否与读取基准同源」。消费方在写入前 MUST 校验
`source`：仅当 `source == "worktree"` 且 `spec_dir` 指向 worktree 内时才可就地写入；
其余（`branch` / `main`）MUST NOT 以主树为落点就地写入。

#### Scenario: 来源标注可判定写回层

- **WHEN** 消费方在写入前读取解析结果的 `source`
- **THEN** 可据 `source == "worktree"` 判定允许就地写入，否则改走打回 / 凭据通道
