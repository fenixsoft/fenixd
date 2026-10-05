## Context

2026-10-06 核查锚点：admin_actions.py:2271 `_exec_grant_env_exemption`（豁免落 AdminStore disposition）；escalation.py:455 `_env_whitewash_gate`（白化门禁，10:27:13.721Z 拒绝实锤）；verdict_check.py:525 `whitewash_violations`；state_machine.py:287（冻结阈值 2 轮）；pipeline.py:1337（verified 唯一自动清除）；adjudication_choices.py（choices 注册点）。场景不可行双证据：场景 feed 1024 原图不缩放+AOSP R API1 过滤；scripts/cfc-emulator-roundtrip.sh:54 EXPECT_MD5 对象错比。既有边界：fix-env-exemption-exit-reachability 已实现（choices 闭环+时序，明示不涉门禁/时效）；fix-verify-loop-convergence 未实现（core 零引用）。STATE 字段键风格沿 core/config.py:297-330 常量先例。

## Goals / Non-Goals

- [x] 豁免签名键化入 STATE + 双门同源消费 + 场景修订出口 + 归因证据要求
- [ ] 不做 spec 级全面豁免；不动握手时序；不动冻结阈值；不做产品代码自动改

## Technical Design

1. STATE 字段与常量：新增 env_exemptions 结构（{scenario_id, failure_signature, granted_at}[]）与字段名常量（单源定义，admin_actions/verdict_check/escalation 共用）；时效锚点沿用既有 TTL 语义。
2. verdict_check.py：whitewash_violations 逐项查有效豁免（场景 id+签名归一化匹配），命中则该项豁免；保持「0-pass 不可白化」与 fail-closed（STATE 读失败=无豁免）。
3. escalation.py：`_env_whitewash_gate` 消费同源锚点，消除「握手认可、门禁拒绝」双门矛盾；双门一致性由同一纯函数提供。
4. admin_actions.py + adjudication_choices.py：豁免写入改走 STATE 字段（disposition 保留审计镜像）；新增 revise_scenario_reverify choice（修订上限默认 2，仅场景定义文件路径白名单，产品代码路径拒绝）。
5. pipeline.py / state_machine.py：修订重验生命周期——冻结集合摘除/重挂、修订 re-entry 先于升级；超限转人工冻结。
6. 防护：签名归一化防同 run 两次重试刷「复现」计数；修订文件路径白名单防借道改产品代码。

## Open Questions

- 失败签名归一化粒度（错误类+场景 id vs 含参数指纹）——过粗易误豁免、过细永不相等，实现时以本案 ENODEV/超时两类校准。