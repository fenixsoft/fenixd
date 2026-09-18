## ADDED Requirements

### Requirement: delete 声明的不可交付形态拒绝

`lint_declared` MUST 对 `kind: delete` 条目施加四类拒绝，使不可校验的删除声明在晋升（drafted → ready）阶段即被拦下，而非留一个恒绿灯的假校验：

1. **路径被 gitignore 排除** —— 守卫基准为实现分支 blob，gitignored 路径不属于任何分支，反判会恒判通过。处方：运行时文件的删除不进 Deliverables 段，由人工在主树执行。
2. **路径在主树不存在** —— 无可删，声明形态错误。
3. **路径是目录** —— 守卫按 blob 校验，目录不可对账。处方：逐个文件声明。
4. **路径解析后不在项目根内**（`~` 展开／`..` 越界／绝对路径归一）—— 任何分支不可交付。

任一命中 → 返回违规并阻止晋升，消息 MUST 含路径、命中的规则与处方。lint 自身故障仍按既有语义 fail-open。

#### Scenario: gitignored 路径上的 delete 拒绝晋升

- **WHEN** 声明段含 `- path: .fenix/hooks/restart-daemon-when-idle.py` + `kind: delete`
- **THEN** `lint_declared` 返回违规，消息含该路径与「gitignored 路径不可作为 delete 交付物」语义，并指明运行时文件删除不进 Deliverables 段
- **AND** spec 停留 drafted，不晋升 ready

#### Scenario: 主树不存在的 delete 拒绝晋升

- **WHEN** 声明段含 `- path: core/ghost.py` + `kind: delete` 且主树无该文件
- **THEN** `lint_declared` 返回违规，消息含「主树不存在，无可删除」语义

#### Scenario: 目录的 delete 拒绝晋升

- **WHEN** 声明段含 `- path: core/legacy/` + `kind: delete`
- **THEN** `lint_declared` 返回违规，消息含「delete 必须是具体文件而非目录」语义

#### Scenario: 仓库外路径的 delete 拒绝晋升

- **WHEN** 声明段含 `- path: ~/configs/app.yaml` + `kind: delete`
- **THEN** `lint_declared` 返回违规，消息含「仓库外路径不可作为 delete 交付物」语义

#### Scenario: 合法 delete 声明通过 lint

- **WHEN** 声明段含 `- path: __init__.py` + `kind: delete` 且该文件是主树中已入库的具体文件
- **THEN** `lint_declared` 不对该条目返回违规

### Requirement: delete 排除出全部软化路径

既有两处「声明与不可交付模式冲突即机械软化为 `reference`」的自动化 MUST 排除 `delete` 条目：

- 晋升期软化（`classify_unsatisfiable` / `soften_declared_kind`，reasoning 前缀 `promotion-soften`）；
- 守卫缺件确定性预分类（reasoning 前缀 `guard-preclassify`）。

软化的语义是「降级为仅审计、不再硬校验」，施加于 `delete` 即等于让「该删」静默消失——恰是本能力要消灭的形态。`delete` 的不可交付形态已由晋升 lint 在更早阶段拒绝，走到软化编排处即说明声明形态异常，MUST 保持原样交由 lint／人工处置，MUST NOT 被改写。

#### Scenario: 晋升软化跳过 delete 条目

- **WHEN** 声明段含 `- path: core/legacy.py` + `kind: delete`，且该路径命中不可交付模式（如被 gitignore 排除）
- **THEN** 该条目 kind MUST NOT 被改写为 `reference`
- **AND** 该条目交由晋升 lint 判定

#### Scenario: 守卫预分类跳过 delete 条目

- **WHEN** 收工守卫返回的违规中含 `kind: delete` 条目，且该路径命中不可交付模式
- **THEN** 预分类 MUST NOT 软化该条目
- **AND** 该条目保留在待处置清单中进入后继流程

#### Scenario: 软化产物不含 delete（防回归断言）

- **WHEN** 对任意含 `delete` 条目的声明段执行晋升软化与守卫预分类
- **THEN** 改写后的声明段中 MUST NOT 存在被软化（kind 由 `delete` 变为 `reference`）的条目

## MODIFIED Requirements

### Requirement: 产出期教学注入

SPEC 起草指引（fenix-new skill 与 spec_gen tasks 工件 instruction）MUST 注入：

- **四类 kind 语义**：`new`=本仓库新建文件；`modify`=修改既有文件；`delete`=让该路径在合并后不存在（仅限入库文件，守卫反判存在性）；`reference`=运行时写入目标/既有引用，非本仓库交付物。
- **四类不可交付模式的 kind 约定**：dist/构建产物 → 锚点文件 + `reference`；gitignored 路径 → 禁 `new/modify/delete`；`~`/仓库外路径 → 禁 `new/modify/delete`；`.fenix/` 运行时文件 → `reference`。
- **明示边界**：`.fenix/` 等 gitignored 运行时文件的**删除不能由 SPEC 交付**——实现 agent 在 worktree 内物理不可达这些文件（worktree 不复制 gitignored 文件），且对主树只读。此类删除 MUST NOT 写进 Deliverables 段，须由人工在主树执行；写进声明段会在晋升 lint 处被拒绝。

#### Scenario: tasks 工件指引含四类 kind 与边界明示

- **WHEN** 调用 `fenix_spec.py instructions tasks --change <name>`
- **THEN** 返回的 instruction 文本含 `delete` 的语义说明、四类不可交付模式的 kind 约定，以及「gitignored 运行时文件的删除不能由 SPEC 交付、须人工在主树执行」的明示

#### Scenario: fenix-new skill 指引含四类 kind 与边界明示

- **WHEN** 阅读 `skills/fenix-new/SKILL.md` 的 tasks.md 生成指引节
- **THEN** 该节含四类 kind 语义表与四类不可交付模式的 kind 约定
- **AND** 该节明确 gitignored 运行时文件的删除不进 Deliverables 段

#### Scenario: 旧处方不再出现

- **WHEN** 检索 `skills/fenix-new/SKILL.md` 与 `schemas/spec-driven/schema.yaml` 的 kind 教学段落
- **THEN** 不存在「删除目标声明 `reference`」一类把删除引导到软校验的表述
