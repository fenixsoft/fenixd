<!-- knowledge: capability=redispatch-loop-governance rev=1 sources=spec/archive/2026-09-22-fix-redispatch-loop-governance -->

# 同因重派熔断与成果继承

对同一 SPEC 的同因重派设熔断上限、重派时继承上一轮现场与成果：既不无限热派空转，也不让每轮从零重做。

## 现行规则

- 同因重派熔断：连续重派达可配置阈值时冻结该 spec（`frozen=True` + `status=blocked`）转人工处置并发人工升级告警，不再派发新一轮。「同因」以机械判据判定，至少覆盖：连续多轮 run 以 `partial` 收工且缺口集合不变；连续多轮判失败且归一化后的归因文案指纹相同。缺口集合或归因指纹各不相同（每轮确有新进展）时不触发熔断，按既有重试通道继续。熔断阈值为可配置项，配置键同步提供 Dashboard 设置界面。
- 熔断解除与还原：人工解冻（`unfreeze_spec`）后同因计数清零、重试从零起算；冻结 error 文案内嵌「原状态 <冻结前状态>」子串，官方解冻通道（`parse_orig_status` → `unfreeze_spec(status=orig)`）据此把 spec 还原为可调度状态并重新派发。
- 重派成果继承：partial 收敛不成立（确有未申报缺口）、或收敛成立但卡在后续门导致需要重派时，重派继承上一轮的 worktree 现场与分支成果（含已提交成果与未提交现场），不从零重建（不新建 worktree、不从 main 重起）。run 层报成功（`result.success=True`)但 spec 层需要重派时不再无条件 `cleanup(success=True)` 清理现场；run 成功且 spec 正常推进（不重派）时既有清理语义不变。
- 与既有预算/豁免机制正交：熔断不覆盖 `_impl_run_budget_used`（保持熔断前真实值，不重置不清零，熔断原因与预算状态在冻结 error 文案中均可读）、不吞预算计数；重派因熔断中止时不走死亡 run 豁免路径（该路径语义为「run 无收工结果」，与同因重派无关）；熔断、实现预算、死亡豁免三者各自独立记账。
- 任务与交付物以函数名 / 字段名 / 配置键锚定，不以绝对行号作为唯一锚点。

## 溯源

- 2026-09-22 fix-redispatch-loop-governance（spec/archive/2026-09-22-fix-redispatch-loop-governance） — 确立同因重派熔断（机械同因判据 + 可配阈值 + 原状态还原解冻）、重派 worktree/分支成果继承、与预算豁免的正交记账
