## ADDED Requirements

### Requirement: pushed 转移触发蒸馏

SPEC 状态经 `approve_push` 成功转移 done→pushed 后，MUST fail-open 派发 `dispatch_distill`（该 SPEC 名，单条）；派发任何异常 MUST NOT 影响 approve_push 主流程的返回值与状态转移结果（与归档触发时代的 fail-open 口径一致）。幂等边界：

- 已 pushed 的回放/并发路径（幂等 skip 分支）MUST NOT 重复派发；
- 非 done 状态（转移被拒）、push 退避期内跳过、SPEC 不存在——均 MUST NOT 派发；
- `commit_archive_move` MUST 不再挂载蒸馏派发（归档移动不产生蒸馏 run）。

#### Scenario: approve_push 成功即派发

- **WHEN** 一个 done 状态的 SPEC 经 approve_push 成功转移为 pushed（人工或 _auto_approve 自动档）
- **THEN** `dispatch_distill` 以该 SPEC 名被调用且返回 dispatched（蒸馏批入队，run 产物开始行落盘）；approve_push 的返回值与状态转移不受派发结果影响

#### Scenario: 幂等回放不重复派发

- **WHEN** approve_push 被并发/回放再次调用且 SPEC 已是 pushed
- **THEN** 幂等 skip 分支返回且不派发蒸馏（同一 pushed 生命周期至多一次触发）

#### Scenario: 归档不再触发

- **WHEN** 任一路径（CLI / dashboard 手动 / daemon 自动归档）完成归档移动
- **THEN** 不派发蒸馏（归档触发已迁移），归档提交内容与既有语义一致

### Requirement: 蒸馏输入目录双态解析

蒸馏链路（`_gate_distill` 存在性检查、`build_distill_prompt` 输入路径、`recover_pending` 恢复重派）MUST 按双态解析蒸馏源目录：`spec/changes/<名>` 优先、`spec/archive/<名>` 兜底（push 后 3 天内蒸馏失败入 pending 台账、恢复重派时 SPEC 可能已归档）。两态下门控放行、prompt 动态段路径、蒸馏 agent 可读输入 MUST 一致成立；目录两态均缺失时 MUST 拒绝派发（reason 区分于既有 archive-dir-missing 语义）。

#### Scenario: push 触发读 changes 目录

- **WHEN** push 触发派发（SPEC 在 spec/changes/、未归档）
- **THEN** 门控放行、prompt 动态段给出 `spec/changes/<名>` 绝对路径，蒸馏 agent 成功读取 SPEC 文档完成蒸馏

#### Scenario: 恢复重派兜底归档目录

- **WHEN** pending 台账中一批在 daemon 重启时恢复重派，且对应 SPEC 已被时效归档（changes/ 无目录、archive/ 有）
- **THEN** 双态探测兜底命中 archive/ 目录，门控放行、prompt 路径指向归档目录，批正常执行

#### Scenario: 双态均缺失拒绝

- **WHEN** 派发名单中某名在 changes/ 与 archive/ 均无目录
- **THEN** 拒绝派发并返回明确 reason，不产生空输入蒸馏 run

### Requirement: 归档改写保持溯源链接自洽

知识页溯源链接（sources 行与正文链接）在蒸馏时 MUST 指向 `spec/changes/<名>/`（push 触发时刻 SPEC 的真实位置）。归档移动成功后的单点 MUST 执行溯源改写 pass：将 `spec/knowledge/` 下该 SPEC 名的链接与 sources 批量改写为 `spec/archive/<date-name>/`，并纳入归档提交（同一 commit 落库）。改写 pass MUST fail-open：异常只告警留痕不阻塞归档主流程。`validate_knowledge` 与 knowledge audit 的链接检查 MUST 对 changes/ 与 archive/ 两态均不误报（链接目标真实存在即合法）。

#### Scenario: 归档时知识页链接迁移

- **WHEN** 一个已有知识页溯源记录的 SPEC（蒸馏于 push 时刻）被归档移动成功
- **THEN** `spec/knowledge/` 下指向 `spec/changes/<名>/` 的链接与 sources 全部改写为 `spec/archive/<date-name>/`，改写与归档移动同一提交落库

#### Scenario: 链接门两态不误报

- **WHEN** 知识页溯源链接指向 spec/changes/<名>/（未归档期）或 spec/archive/<名>/（归档后），且目标目录真实存在
- **THEN** validate_knowledge 与 knowledge audit 均不报违规（两态等价合法）

#### Scenario: 改写失败不阻塞归档

- **WHEN** 溯源改写 pass 执行异常（如 spec/knowledge/ 不可写）
- **THEN** 归档主流程正常完成（目录移动与提交照常），异常告警留痕（日志），不产生半提交
