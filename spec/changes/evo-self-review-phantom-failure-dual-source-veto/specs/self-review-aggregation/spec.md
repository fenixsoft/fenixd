# self-review-aggregation：幻影失败结构化双源否决

## ADDED Requirements

### Requirement: error 终态样本双源否决

日报聚合对 run 文件尾 error 终态导致的 failed 分类，当 detail 为 Exit code / CLI 错误形态时，SHALL 查 daemon 侧 run_metrics 终态做交叉裁决：terminal=success（salvage/产物直读登记）SHALL 改计 success 并写 self_review_phantom_failure 告警；查无 run_metrics 账面行时 SHALL 保守保持 failed。

#### Scenario: salvage 成功被误计为失败

- WHEN run 文件尾为 error 终态（Exit code: 1 形态）且 daemon run_metrics terminal=success
- THEN 该样本改计 success 并写 self_review_phantom_failure 告警

#### Scenario: 查无账面行保守保持失败

- WHEN run 文件尾为 error 终态且查无 run_metrics 账面行
- THEN 保持 failed 分类不改动

### Requirement: marker= 样本纳入双源否决

marker= 命中（失败词复述）样本 SHALL 接入同一双源否决：daemon terminal=success 即改计 success 并写 self_review_phantom_failure 告警；原「marker= 与 error 终态 MUST NOT 纳入守卫」的排除约定由「daemon 终态权威裁决」取代。

#### Scenario: 失败词复述被否决

- WHEN marker= 命中样本的 daemon run_metrics terminal=success
- THEN 该样本改计 success 并写 self_review_phantom_failure 告警

### Requirement: salvage 路径指标透传

产物直读 / salvage 登记路径写入的 run_metrics 行 SHALL 透传档案侧真实值，不再记 turns=0/cost=null：total_cost_usd ← 档案 result 事件顶层 total_cost_usd；turns ← daemon 日志 context metrics 行（「context metrics: turns=N」结构化行；档案 result 事件 num_turns 为 text 轮口径，非本条目标轮次）。任一源查无/解析失败时 SHALL 保持现状记 0 并 DEBUG 留痕，不阻塞落地主链。

#### Scenario: 指标行与档案侧一致

- WHEN 产物直读路径按成功落地一个 run（档案 result 事件含 total_cost_usd、daemon 日志含该 run 的 context metrics 行）
- THEN 该 run 的 run_metrics 行 cost 等于档案 result 事件的 total_cost_usd，turns 等于 context metrics 行的 turns 值

### Requirement: 真实失败不受守卫影响

daemon run_metrics terminal=error 的样本 SHALL 保持 failed；守卫只否决「过程账失败但终态账成功」的分叉样本。

#### Scenario: 真实失败保持计数

- WHEN run 文件尾 error 终态且 daemon run_metrics terminal=error
- THEN 保持 failed 分类，不写幻影告警