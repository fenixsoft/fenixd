# relocation-writeback-layer — 声明修正写回层契约

## ADDED Requirements

### Requirement: 修正写回层与读取基准同源

交付物声明的机械修正（`typo` 路径改写、`reference` kind 软化、条目删除）在**写入**时，
其落点 MUST 与守卫/裁决的**声明读取基准**同源——即**生效声明命中的那一层**
（`resolve_effective_declaration` 返回的 `source`）：

- `source == "worktree"`：改写并提交到**该 worktree**（分支）；
- `source == "main"`：改写并提交到**主树**——此时前两层均未命中，守卫读取基准**就是
  主树**，就地写入即同源，不构成错层；
- `source == "branch"`（`spec_dir` 为 `None`，声明只存在于分支对象库、无落盘位置）：
  MUST NOT 以主树 `tasks.md` 为落点「就地改写」并视为生效；修正 MUST 交由实现方在
  分支上续做（走既有缺件打回 / 重定位凭据通道），且该条裁决 MUST 落 dispute 审计流。

系统 MUST NOT 在「守卫读取基准为 worktree/分支」的同时把修正只写主树——那会使修正
在下一轮被判读不回来（写读错层根因，add-code-review-auto-fix 事故实证）。

本要求 MUST 覆盖 `tasks.md` 声明段的**全部**写入点（judge 执行的 typo/reference/删除
分支、`_preclassify_missing` 确定性软化、`_preclassify_orphan` 删除、晋升期软化），
任一写入点未按 `source` 判定落点即为漏网。

#### Scenario: 有 worktree 时修正写进工作树

- **GIVEN** SPEC 的声明含笔误路径，实现 worktree 存在于分支 `fenix/<spec>-<ts>`
- **WHEN** judge 裁决 `typo` 并执行修正
- **THEN** 改写作用于该 worktree 内的 `spec/changes/<spec>/tasks.md`
- **AND** 变更提交到该分支（非主树）

#### Scenario: 主树为命中层时就地主树写入（不得禁止）

- **GIVEN** 无实现 worktree，且分支对象库无该 SPEC 的声明段
- **WHEN** judge 裁决 `typo` 并执行修正
- **THEN** 改写作用于主树 `spec/changes/<spec>/tasks.md` 并提交
- **AND** 守卫复读（同为 `source == "main"`）可见该修正（同源）

#### Scenario: 分支为唯一命中层时不写主树假装修正

- **GIVEN** 实现 worktree 已清理，守卫读取命中分支版本（`source == "branch"`，
  `spec_dir` 为 `None`）
- **WHEN** judge 裁决 `typo`
- **THEN** 系统 MUST NOT 仅改主树 `tasks.md` 并视修正完成
- **AND** 修正落入实现方续做通道（打回重派 / 凭据登记），该条裁决落 dispute 审计流，
  守卫复读仍以分支版本为准

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
`typo`/`relocation` 凭据、**且该凭据携带的替代路径在实现分支 HEAD 存在**时方可核销；
凭据存在但替代路径无据（不存在/取不到）MUST NOT 核销。核销判定 MUST 能取得凭据中的
替代路径（布尔型「是否有凭据」判定不足以完成该校验）。

核销的作用域 MUST 限于 `violation == "missing"` 条目：`undeleted` / `removed` 违规
MUST NOT 被本核准销吞掉（其豁免仍走既有收缩防护通道）。

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

该计数 MUST 使用**独立持久字段**，MUST NOT 复用会被恢复续做/阻塞复位清零的通用重试
计数（`_retry_count`：`state_machine.py:1729` 恢复续做分支与 `:1469` 重建分支均写 `0`，
而 blocked 会被 `resolve_env_blocked_reset_path` 复位续走重实现）——否则计数在每轮
复位后归零，熔断永不触发（事故态实证：31 小时在飞期间 `_retry_count` 恒为 `0`）。该
计数 MUST NOT 随 blocked→ready / 恢复续做清零，仅在两处清零：本形态修正复检通过、
或该 SPEC 退出本形态。

#### Scenario: 连续复发升 blocked

- **GIVEN** 某路径 `typo` 修正后连续 N 轮仍被判缺件（N = 配置上限）
- **WHEN** 第 N 轮再次复发
- **THEN** SPEC 置 blocked，error 说明「修正未生效于读取基准」
- **AND** 不再自动重派实现
