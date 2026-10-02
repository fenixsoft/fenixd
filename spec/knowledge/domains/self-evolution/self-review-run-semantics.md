<!-- knowledge: capability=self-review-run-semantics rev=2 sources=spec/archive/2026-09-19-evo-add-self-review-run-semantics,spec/archive/2026-10-03-evo-fix-self-review-phantom-failed-samples -->

# 自省 run 终态的业务失败语义

进程正常终止不等于业务成功：自省对 result 型终态解析内容，命中业务失败标记即判失败，终止态与成功态解耦。

## 现行规则

- result 型终态的业务失败解析：自省 run 分类对终态类型为 `result` 的 run 进一步解析其 result 内容——命中设计固化的业务失败标记清单（含『SPEC 内容缺失』『无法实现』『预算耗尽』『零交付/零产出』等价不变量），或同一 run 的信号证据（终态邻近窗口内、剥除 assistant 收工叙事回声行后，口径见 [self-review](self-review.md)）含 budget-exhausted / spec-missing 类结构性信号时，判为 failed（或设计的废弃类目）而非 succeeded；不得仅凭进程正常终止判定业务成功。
- 双源交叉护栏：result 文本未含完整标记短语、但剥除 assistant 回声行后的信号证据存在 budget-exhausted/spec-missing 结构性信号 → 按信号判失败（护栏）；文本含标记但无信号 → 按文本判失败（保守）。仅存在于 result 正文及其 assistant 回声行中的失败词不构成结构性信号。
- 真实成功不受影响：result 文本为正常收尾总结且无业务失败标记的 run 照常计 succeeded。
- 失败可追溯：分类为业务失败的 run 在统计/样本输出中保留可追溯依据（run_id + 命中标记或信号摘要），便于审计与回源。
- 统计输出 schema 兼容：沿用 succeeded/failed 类目，无新增 UI 依赖、无新配置键。

## 溯源

- 2026-09-19 evo-add-self-review-run-semantics（spec/archive/2026-09-19-evo-add-self-review-run-semantics） — 自省成功判据纳入业务失败语义（盲派空 spec run 自述「SPEC 内容缺失」曾被计成功、浪费规模被系统性低估）
- 2026-10-03 evo-fix-self-review-phantom-failed-samples（spec/archive/2026-10-03-evo-fix-self-review-phantom-failed-samples） — 信号护栏口径收窄：结构性信号以剥除 assistant 收工回声行后的终态邻近窗口为准，正文及回声行中的失败词不再构成信号证据
