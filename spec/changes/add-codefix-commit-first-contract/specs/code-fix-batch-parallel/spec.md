# code-fix-batch-parallel delta：单次提交契约改为边修复边提交

本变更改写 `code-fix-batch-parallel` 能力「汇总后一次验证一次提交」requirement
（活源：`spec/changes/add-codefix-batch-parallel/specs/code-fix-batch-parallel/spec.md`）。
原「验证先行 + 单次提交、MUST NOT 多次提交」与 add-codefix-commit-first-contract 的
「先 commit 再验证」提示词契约直接互斥（后者为搁浅批根因治理：验证丢后台致回合结束
时改动从未 commit）；改为「边修复边提交、收尾一次验证」。批内并行处置协议、组级增量
落盘与单写者、子代理失败兜底、子代理禁提交等其余 requirement 不变。

## MODIFIED Requirements

### Requirement: 边修复边提交、收尾一次验证

全部组落盘完成后，orchestrator MUST 按触碰面做**一次**定向验证（仅前端→tsc+前端单测；仅 Python→定向 pytest；混合→两者）。验证 MUST NOT 作为提交的前置条件：orchestrator MUST 在改动落盘后尽早提交（修复结果逐组落盘即逐组提交，或收尾一次提交，均合法；提交信息可含全批 item_id），验证于提交之后进行、结果用于回归门前的自查补修（补修改动 MUST 再次 commit）。MUST NOT 逐组验证；回合结束前 worktree 工作区必须干净（全部改动已 commit，机械保障见 `code-fix-lane`「收尾 salvage commit」）。

#### Scenario: 边修复边提交、验证不阻塞

- **WHEN** 并行批全部组落盘完成
- **THEN** 提交先于验证完成（逐组或收尾一次提交均可），随后恰好一次定向验证；验证发现问题时补修并追加 commit，框架回归+合回流程与现状完全一致
