# verifier-infra-death-triage Specification

## Purpose

验证车道 agent 本体的进程级基础设施死亡（0 assistant 轮/启动期秒死）与真实验证不通过分流出不同出口：前者走限次廉价重派与超限暂挂，不再被 fail-closed 消费误判成 bug-found 原地打回。

## Requirements

### Requirement: 进程级死亡不进 bug-found 出口

verifier run 终局失败且满足进程级死亡特征（终局结果 assistant 轮数为 0，或全部 attempt 存活时长低于秒挂判定阈值——存活口径以终局结果 duration_seconds 判读，其为 run 级总存活、构成全部 attempt 存活的严格上界；attempt 级侧账（runner `_record_instant_fail`）仅辅助标注）时 MUST NOT 判 bug-found：不触发原地打回、不消耗实现尝试预算；有 assistant 轮次且存活达秒挂阈值、或场景执行有产物的正常失败路径 MUST NOT 变化。

#### Scenario: 启动期 ENOENT 秒死

- **WHEN** verifier 全部 attempt 因启动期错误（如临时补丁文件缺失）秒死、终局 0 assistant 轮 0 token
- **THEN** 不判 bug-found，按 infra 台账限次重派验证

#### Scenario: 真实验证失败不回归

- **WHEN** verifier 正常执行（有 assistant 轮次）后产出失败裁决或超轮次失败
- **THEN** 既有 bug-found/降级路径不变

### Requirement: infra 台账限次重派

分流命中的验证失败 MUST 复用既有 infra-retry 台账语义：限次（缺省 2 次）廉价重派，不计 env 冻结轮、不产生 admin 升级；台账清零点与既有验证 PASS + unfreeze_spec 清单同点，MUST NOT 新增平行台账。

#### Scenario: 限次内重派

- **WHEN** 分流命中且台账未达阈值
- **THEN** 直接重派验证，不递增 env 冻结轮、不呼叫 admin

#### Scenario: 重派成功清零

- **WHEN** 重派后验证 PASS
- **THEN** 台账清零，后续 infra 死亡重新计数

### Requirement: 超限验证暂挂

重派超限 MUST 置验证暂挂（blocked+frozen+admin 信号）而非 bug-found，并保留 reclassify_infra_rounds 人工回拨兜底。

#### Scenario: 超限转人工

- **WHEN** 分流连续命中达台账阈值仍失败
- **THEN** 冻结 spec 等 admin 处置，不产生原地打回

### Requirement: 终局轮次回填

runner 构造的终局失败结果 MUST 回填真实累计 assistant 轮数（现 _exhausted_result 恒缺省 0），使消费层可区分「全无产出」与「有进度后失败」；verifier 车道结果对象 MUST 带结构化 stderr_tail/exit_code（对齐 spec-review 车道既有回填机制）。

#### Scenario: 轮次可判别

- **WHEN** 多 attempt run 终局失败
- **THEN** 结果对象 turns_used 反映真实累计轮数，与 context metrics 口径一致