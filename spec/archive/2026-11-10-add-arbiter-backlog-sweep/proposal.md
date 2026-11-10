## Why

`add-arbiter-lane` 的触发面是事件驱动的（挂 `freeze_for_human` 与 `_send_human_escalation_alert` 两个咽喉，事件发生时开火），对**已发生**的存量冻结无效——冻结事件在 Arbiter 存在之前已经流过咽喉。首例即本设计动因本身：`evo-refine-midflight-outlier-dims`（2026-10-30 14:52Z 冻结，正是 Arbiter 白名单①类原型案）。需要一条存量回扫路径，使 Arbiter 上线后能吃掉历史欠账，并以该案作为首个真实处置对象（比构造 fixture 更有说服力的验收）。

## What Changes

- `core/pm_engine/arbiter.py` 新增启动回扫入口：daemon 启动后（`arbiter.enabled=true`）与 config 热更新 disabled→enabled 跃迁时各执行一次。
- 回扫判据：STATE 中 `frozen=true` 且 `admin_alerts` 存在同 spec 未处理（pending）机器升级告警（freeze_for_human 冻结+告警成对语义的反查）；排除 `frozen_until` 非空的定时冻结。
- 命中者走既有 dedup/单飞/预算管线入队派发，幂等由同签名 dedup 兜底（回扫与事件触发竞写同签名不重复派发）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `arbiter-lane`（活跃于 `spec/changes/add-arbiter-lane/specs/arbiter-lane/spec.md`）：「触发面与改道注册」需求增加存量回扫来源——触发面从「事件驱动」扩展为「事件驱动 + 启用/启动时一次性存量回扫」，排除表与 dedup/单飞语义不变。

## Impact

- 修改：`core/pm_engine/arbiter.py`（回扫入口，复用 add-arbiter-lane 建立的派发管线——经 depends_on 保证本 SPEC 派发时该文件已存在）。
- 新增：`tests/test_arbiter_backlog_sweep.py`。
- 生效：合并后需 daemon 重启加载（交付 restart_request 信号，supervisor 消费）。
- 预期首个处置对象：`evo-refine-midflight-outlier-dims`（冻结中，含 pending 升级告警）。
