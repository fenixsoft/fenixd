## ADDED Requirements

### Requirement: 修复推进豁免额度

框架 SHALL 在修复申报受理时为该 spec 置一次性 judge 重跑豁免旗标；judge 派发门在 bump 计数后判定超上限时，若豁免旗标在位，SHALL 消费该旗标并放行本次 judge 派发，不触发 judge_rerun_cap 冻结。

- 豁免旗标 MUST 仅由修复申报受理点置位（`_record_repair_claim` 同一原子写），MUST NOT 接受任何人工或复位通道置位。
- 每次修复申报至多置一枚旗标，消费即清；spec 生命周期豁免总消费次数 MUST 封顶（默认 3 次），超出封顶后受理点不再置位。
- 豁免旗标与豁免计数 MUST 随 verified 落定、人工 unfreeze_spec、admin 手动清零三类终态清零点成对清除。
- 主计数 `_judge_rerun_count` 语义 MUST NOT 改变：豁免轮主计数照常累计，MUST NOT 回退（保持「打回轮计数跨轮累计直至上限」语义）。

#### Scenario: 修复闭环后的首轮裁决不再冻结

- **WHEN** 某 spec 的 `_judge_rerun_count` 已达 5，随后 impl 修复申报被受理（置豁免旗标），下一轮 judge 派发 bump 后 count=6
- **THEN** 派发门消费豁免旗标并放行本次 judge 派发，不写 judge_rerun_cap 冻结、主计数照常累计为 6

#### Scenario: 豁免封顶后恢复硬上限

- **WHEN** 某 spec 的豁免总消费次数已达封顶值，修复申报受理不再置旗标，judge 派发 bump 后 count 超上限
- **THEN** 按现行 `_judge_hard_cap_freeze` 冻结流程处理（error、`_judge_cap_frozen`、升级告警均不变）

### Requirement: 冻结告警附失败集轨迹

`_judge_hard_cap_freeze` 写冻结告警时 SHALL 在 evidence 追加轮内失败集轨迹（verdict_stability 侧车各轮 failed_ids 序列与当轮 pass/failed 统计），人工解冻决策可直接判断失败集是否收缩。

#### Scenario: 冻结 evidence 含失败集轨迹

- **WHEN** judge 派发门触发 `_judge_hard_cap_freeze`
- **THEN** 冻结 evidence 除既有修复预算字段外，含 verdict_stability 轮内 failed_ids 序列；侧车缺失时该段降级省略、不阻塞冻结本身