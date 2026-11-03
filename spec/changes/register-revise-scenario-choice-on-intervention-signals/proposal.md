# manual-intervention/verify_env_blocked 信号桶注册 revise_scenario_reverify 裁决选项

## Why

结构性缺口已两次实弹发作（2026-10-30 evo-refine-midflight-outlier-dims、2026-11-03 add-knowledge-inbox-pipeline）：revise_scenario_reverify 仅注册于 inconclusive_loop 桶，而 Administrator 对场景争议类升级告警的消费信号是 manual-intervention/verify_env_blocked，resolve_choice 的 scoped-no-reverse 守卫（有意防御，不应拆除）导致「载荷完美也必被拒」，每次都烧满整个 admin run（本次 605s/$1.79）再冻结转人工。fix-admin-choice-payload-and-scenario-pairing 已修载荷通道（requires_payload 落地），本提案补同一缺口族的注册矩阵余量：把该 choice 以 requires_payload=True 形态注册进场景争议会流经的信号桶，让 admin 自动处置通道真正可达场景修订出口。

## What Changes

- （arbiter 提案待人工成文：本文件为调查报告提案的最小诚实成文，补全 What Changes / Capabilities / Impact 后走既有晋升流程）

## Capabilities

### New Capabilities

- `<capability>`: （待成文）

### Modified Capabilities

（无）

## Impact

（待成文）

---

- 立项来源：Arbiter 调查（run_id=None，signature=add-knowledge-inbox-pipeline::verify_env_blocked，source=startup）
- 立项时间：2026-11-03T11:31:05.706642+00:00
