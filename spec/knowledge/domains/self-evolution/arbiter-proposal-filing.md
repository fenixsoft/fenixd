# arbiter 处置立项与提案物化

<!-- knowledge: capability=arbiter-proposal-filing rev=1
     sources=spec/archive/fix-arbiter-proposal-materialize-spec-dir-1793497541 -->

arbiter 车道对评审尝试耗尽等积压状态的兜底处置之一，是自动立项一条 drafted SPEC；本页约束该立项通道的目录物化契约、失败语义与台账留痕。

## 规则

- **先物化后注册**：arbiter 立项落 drafted 前，必须先物化 `spec/changes/<name>/` 目录（proposal.md 加原生脚手架）再向 STATE 注册条目。STATE 条目不得脱离其实体目录单独存在——无目录条目（幽灵条目）对用户不可见，spec-review 因目录缺失无法落账评审结论（以 rejected（format）收口），评审车道被冻结空转。
- **物化失败跳过立项**：目录物化失败时本次立项作废，仅在处置台账记 `proposal-materialize-failed` 记录，不产生任何无目录的 STATE 条目。
- **重放幂等**：目标 proposal.md 已存在即跳过物化，同一提案重放不重建、不覆盖目录。
- **提案最小成文**：物化的 proposal.md 为最小诚实成文（Why=立项理由、来源=触发签名与 run_id），不带 tasks.md 与 specs delta；晋升 lint 因此拦截自动晋升，条目停在 drafted 待人工成文补全。
- **台账留痕**：每次立项与跳过处置均在 `.fenix/arbiter_ledger.jsonl`（append-only）落一条记录，`action_or_upgrade` 字段记处置动作（如「立项落 drafted: <name>」）。

## 关键行为

立项序列：arbiter 触发处置立项 → `_materialize_proposal` 物化目录（复用 `core.spec_gen.new_change` 原生脚手架，名称校验与 `.spec.yaml` 同源；物化后 best-effort 单目录 git 提交，提交失败仅 WARNING 不阻断，未跟踪目录不干扰 STATE 语义）→ `add_spec` 注册 status=drafted 条目 → 台账落 `spec-proposed`。drafted 条目走既有 evo ready 人审门，arbiter 立项不自动晋升。

## 溯源

- 2026-11-01 fix-arbiter-proposal-materialize-spec-dir-1793497541（spec/archive/fix-arbiter-proposal-materialize-spec-dir-1793497541） — 处置留痕归档（非方案成文，原条目系幽灵条目的清退载体）：固化 arbiter 立项物化契约（先物化后注册、物化失败跳过立项只记台账、重放幂等）与幽灵条目缺陷形态。
