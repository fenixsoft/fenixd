# arbiter 处置立项与提案物化（已退役）

<!-- knowledge: capability=arbiter-proposal-filing rev=2
     sources=spec/archive/fix-arbiter-proposal-materialize-spec-dir-1793497541,spec/knowledge/_inbox/done/arbiter-filing-retire-gap-todo-routing.md -->

arbiter 车道不设自动立项通道（权限红线禁立项，详见 admin-ops 域 [arbiter-lane](../admin-ops/arbiter-lane.md)）；本页只承载该退役面的台账历史兼容语义与 STATE 注册通用纪律。

## 规则

- **arbiter 零立项**：arbiter 车道不创建、不注册任何 SPEC——无 `spec/changes` 目录物化写点、无提案消费/节流机制、无 STATE 条目写入；台账 kind `spec-proposed` / `proposal-dedup` / `proposal-throttled` 不再产生。框架缺口发现统一走调查报告 `gaps` 数组记入 `.fenix/todo.md`，由自进化车道评估立项（见 admin-ops 域 arbiter-lane 页）。
- **台账 append-only 历史兼容**：存量 `spec-proposed` 台账条目原样保留，不做清洗、不改写。
- **先物化后注册是通用纪律**：任何 STATE 注册写点必须先物化实体目录再注册条目。STATE 条目不得脱离其实体目录单独存在——无目录条目（幽灵条目）对用户不可见，spec-review 因目录缺失无法落账评审结论（以 rejected（format）收口），评审车道被冻结空转。该纪律适用于所有 STATE 注册写点，不是任何特定车道的特有契约。

## 溯源

- 2026-11-01 fix-arbiter-proposal-materialize-spec-dir-1793497541（spec/archive/fix-arbiter-proposal-materialize-spec-dir-1793497541） — 处置留痕归档（非方案成文，原条目系幽灵条目的清退载体）：固化 arbiter 立项物化契约（先物化后注册、物化失败跳过立项只记台账、重放幂等）与幽灵条目缺陷形态。
- 2026-11-03 arbiter-filing-retire-gap-todo-routing（spec/knowledge/_inbox/done/arbiter-filing-retire-gap-todo-routing.md） — 折叠 arbiter 立项通道整体退役：提案物化/消费写点与节流常量删除，原物化契约规则（先物化后注册、物化失败跳过立项、重放幂等、提案最小成文）随通道退役失效，本页改写为退役态（台账历史兼容 + 幽灵条目教训通用化为 STATE 注册纪律）。
