# relocation-writeback-layer — 声明修正写回层契约

## ADDED Requirements

### Requirement: 修正写回层与读取基准同源

交付物声明的机械修正（`typo` 路径改写、`reference` kind 软化、条目删除）在**写入**时，
其落点 MUST 与守卫/裁决的**声明读取基准**同源——即「生效声明所在工作树」：

- 实现 worktree 存在时：改写并提交到**该 worktree**（分支）；
- 实现 worktree 不存在、读取命中分支版本时：修正 MUST 交由实现方在分支上续做
  （走既有缺件打回 / 重定位凭据通道），MUST NOT 直接改主树假装修正已生效。

系统 MUST NOT 在「读取优先序为 worktree/分支」的同时把修正只写主树——那会使修正在
下一轮被判读不回来（写读错层根因，add-code-review-auto-fix 事故实证）。

#### Scenario: 有 worktree 时修正写进工作树

- **GIVEN** SPEC 的声明含笔误路径，实现 worktree 存在于分支 `fenix/<spec>-<ts>`
- **WHEN** judge 裁决 `typo` 并执行修正
- **THEN** 改写作用于该 worktree 内的 `spec/changes/<spec>/tasks.md`
- **AND** 变更提交到该分支（非主树）

#### Scenario: 无 worktree 时不写主树假装修正

- **GIVEN** 实现 worktree 已清理，守卫读取命中分支版本
- **WHEN** judge 裁决 `typo`
- **THEN** 系统 MUST NOT 仅改主树 `tasks.md` 并视修正完成
- **AND** 修正落入实现方续做通道（打回重派 / 凭据登记），守卫复读仍以分支版本为准

### Requirement: 修正后读取一致性复检

每次声明修正执行后，系统 MUST 以**守卫读取基准**（生效声明解析入口）复检：被修正的
旧路径不再作为生效声明的硬校验项（不再出现 `missing`）。

复检不一致（读取仍是旧路径）MUST 记入该次处置的 error 明细并告警，MUST NOT 静默销账
——静默销账会让打回循环无人可见地持续烧预算。

#### Scenario: 复检一致放行

- **WHEN** 修正写入生效声明所在工作树后复检
- **THEN** 生效声明中旧路径已被替代路径取代
- **AND** 复检通过，正常推进合并

#### Scenario: 复检不一致告警

- **GIVEN** 修正只落到非读取基准层（如主树），分支/worktree 版本仍含旧路径
- **WHEN** 复检以生效声明解析入口读取
- **THEN** 仍读到旧路径
- **AND** 记入 error 明细 + 告警，MUST NOT 判为修正成功

### Requirement: 跨轮残留凭据核销（脱困）

守卫读取到的缺件路径，若在**跨 run 持久的 dispute 审计流**中已存在该路径的 `typo`
裁决或重定位凭据（旧路径 → 替代路径），则系统 MUST 以**凭据核销**为收敛动作：该路径
不再要求存在，MUST NOT 仅因「本轮无新凭据」而无界重派。

凭据核销 MUST NOT 放行「路径确从未落地」的假缺件——仅当审计流中该旧路径确有
`typo`/`relocation` 凭据且给出替代路径时方可核销。

#### Scenario: 跨轮残留凭据核销

- **GIVEN** 上一轮 judge 已对 `pages/settings/X.tsx` 落册 `typo` 凭据（替代路径
  `pages/projects/X.tsx`），本轮未 merge-back 致守卫再次读到旧路径缺件
- **WHEN** 守卫/裁决处理该缺件
- **THEN** 依据在册凭据核销，不重派实现、不 blocked

#### Scenario: 无凭据不回退无限重派

- **GIVEN** 缺件路径在审计流无任何 typo/重定位凭据
- **WHEN** 处理缺件
- **THEN** 走既有缺件处置（终审 / 打回），不受本核准销条款影响

### Requirement: 复发熔断

同一 SPEC 同一路径在 `typo` 修正后连续多轮仍被守卫判缺件（读取基准未对齐的迹象）
时，系统 MUST 计数并在达到配置上限后 **blocked 待人工**，MUST NOT 无界重派继续烧预算。

#### Scenario: 连续复发升 blocked

- **GIVEN** 某路径 `typo` 修正后连续 N 轮仍被判缺件（N = 配置上限）
- **WHEN** 第 N 轮再次复发
- **THEN** SPEC 置 blocked，error 说明「修正未生效于读取基准」
- **AND** 不再自动重派实现
