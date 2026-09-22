# declaration-relocation-protocol — 增量规格（写回层对齐）

## MODIFIED Requirements

### Requirement: 重定位机械执行与审计

重定位 MUST 机械执行（不经 Agent 手改文档）：将生效声明中旧路径确定性替换为
替代路径（同名去重，与既有 `replace_declared_path` 语义一致），改写目标与提交根 MUST
为**生效声明命中的那一层**——与守卫读取基准同源：worktree 命中 → 该 worktree（分支
提交）；主树命中（`source == "main"`，前两层未命中）→ 主树 `spec_dir`，此时主树即
守卫读取基准，就地写入不构成错层。worktree 来源时 MUST NOT 另行单独写主树声明
（主树对齐由 merge-back 携带分支提交完成）。

当**无实现 worktree 且读取命中分支版本**（`source == "branch"`，`spec_dir` 为 `None`）
时，重定位 MUST NOT 通过回落写主树来「就地生效」（主树不是本轮读取层，改了也读不回来）；
此时 MUST 走既有缺件打回 / 凭据登记通道，由实现方在分支上续做（见
`relocation-writeback-layer` 的写回层契约）。

每次重定位 MUST 落 dispute 审计流，含：旧路径、替代路径、来源标注、触发 run id、
声明改写前后 diff、时间戳。人工可据审计复核与回滚。

修正执行后 MUST 以生效声明解析入口复检旧路径不再作为硬校验项；复检不一致（写读错层）
MUST 告警并记 error 明细，MUST NOT 静默放行。

#### Scenario: 重定位替换并留痕

- **WHEN** 三要素齐备的重定位执行
- **THEN** 生效声明旧路径被替换为替代路径
- **AND** 改写作用于生效声明所在工作树（worktree → 分支提交路径）
- **AND** dispute 审计流新增条目含旧/新路径、来源、run id 与前后 diff

#### Scenario: 无 worktree 时不写主树就地生效

- **GIVEN** 实现 worktree 已清理，读取命中分支版本（`source == "branch"`）
- **WHEN** 执行重定位
- **THEN** MUST NOT 仅改主树 `tasks.md` 作为重定位落点
- **AND** 走打回 / 凭据登记通道，由实现方在分支上对齐声明

#### Scenario: 主树命中时就地主树改写

- **GIVEN** 无 worktree 且分支版本不含该 SPEC 声明段（解析命中主树）
- **WHEN** 执行重定位
- **THEN** 改写作用于主树 `spec/changes/<spec>/tasks.md` 并提交主树
- **AND** 守卫复读（同为 `source == "main"`）可见该改写

#### Scenario: 审计可回滚

- **WHEN** 人工判定某次重定位有误
- **THEN** 可据审计中的前后 diff 恢复声明段原文并触发重派
