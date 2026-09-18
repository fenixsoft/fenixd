# deliverable-declaration-resolution — 交付物声明解析契约

## ADDED Requirements

### Requirement: 声明解析单一权威源

系统 MUST 提供唯一入口解析「某 SPEC 在当下适用的交付物声明集合」，所有消费方
（收工守卫、晋升 lint、预分类、裁决、提示词组装、fast-track 快照、重定位）MUST
经该入口读取，MUST NOT 由各消费点自行拼接 `project_root/spec/changes/<spec>/`
路径直读主树——杜绝「同一份声明、多个读取基准」的错层。

解析入口 MUST 接收 spec 名与可选分支/worktree 上下文，返回与既有
`extract_declared` 同构的结果（`deliverables` / `references` 两组，保序去重）。

#### Scenario: 消费方统一经入口读取

- **WHEN** 任意消费点需要某 SPEC 的声明集合
- **THEN** 它调用统一解析入口并传入自身持有的上下文（分支名 / worktree 路径 / 无）
- **AND** 不出现该消费点自行读取 `project_root/spec/changes/<spec>/tasks.md` 的路径拼接

#### Scenario: 解析结果与既有提取器同构

- **WHEN** 统一入口在给定上下文下解析声明
- **THEN** 返回结构为 `{"deliverables": [...], "references": [...]}`
- **AND** 条目按首见保序、重复路径去重（与既有 `extract_declared` 语义一致）

### Requirement: 分层解析优先序

声明解析 MUST 按固定优先序分层：**分支 / worktree 版本优先**（实现期真实在测
的那份），在分支/worktree 不可用或不含声明段时回退主树版本。读取分支版本 MUST
以只读方式（如 `git show <branch>:spec/changes/<spec>/tasks.md`）或 worktree
内文件读取，MUST NOT 写主树。

回退 MUST 保持 fail-safe：分支读取失败（非零退出、超时、路径不存在）或解析异常
→ 回退主树；两处均不可用 → 返回空结果（等价「无声明段」，守卫跳过），并审计留痕
说明回退去向。

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

### Requirement: 可信基线快照

系统 MUST 在实现 run 派发时，将当时**主树**的声明集合快照持久化到实现 Agent
不可触及的位置（如 `.fenix/verify-progress/<spec>/declaration-baseline.json`），
作为该轮「可信基线」。快照 MUST 记录：声明条目（path + kind）、快照时刻、触发
run id。

快照 MUST NOT 位于 worktree 内、MUST NOT 由实现 Agent 路径写入——它是收缩防护
（见 `implementer-deliverable-gate`）的独立参照系，读取方为守卫/裁决流水线。

#### Scenario: 派发时落基线快照

- **WHEN** daemon 派发某 SPEC 的实现 run
- **THEN** `.fenix/verify-progress/<spec>/declaration-baseline.json` 写入当时的
  主树声明条目（path + kind）与 run id
- **AND** 该文件不在 worktree 内

#### Scenario: 快照写入失败不阻塞派发

- **WHEN** 基线快照写入异常（磁盘/权限）
- **THEN** 派发照常进行，WARNING 留痕
- **AND** 收缩防护对该轮降级为「无基线可用」保守策略（见收工守卫的降级语义）

### Requirement: 解析成本契约

声明解析 MUST 为纯文件/对象库读取（worktree 文件读或 `git show`/`git cat-file`），
MUST NOT 触发 LLM 调用、测试执行或网络请求。

#### Scenario: 零额外成本

- **WHEN** 统一解析入口执行
- **THEN** 无 LLM / 测试 / 网络调用
