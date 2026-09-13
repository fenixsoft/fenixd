## Why

fast-track 模式按统一 3.5h/6 次 extension 预算派发 implementer，无任务规模预估。fix-root-init-import-shadow 实证：同一 spec 三次 12600s 超时（fenixd.log 4163/4733/5278 行，合计 10.5h 空转），第三次已跑满 91 rounds 仍被 extension budget 2/2 耗尽即杀；对照同窗口较小 spec（fix-dispatch-wakeup-gap 等）均单轮成功，规模相关性明显。add-verify-preflight-gate 已覆盖入口存在性预检、add-turn-limit-anchor-c 已覆盖轮数锚点，但均未覆盖『任务规模 → 预算档位』映射。任何真实项目的大任务面 spec 在 fast-track 下都会被同规格对待，反复烧满硬限。

## What Changes

- 新增 fast-track 派发前规模预检：读 spec 的 tasks.md 任务条数 / spec 目录变更面作为轻度静态预估，超阈值时自动降级 full 模式或提高 extension 预算。
- 新增「extension 末位自动保全」：fast-track 超时预算用尽前（extension #2 收尾前，如剩余时间窗口 <30min）自动触发一次 WIP checkpoint 保全，避免已完成轮次工作随超时作废。复用既有 `commit_wip_checkpoint`（add-impl-wip-checkpoint，尽力而为、失败降级、不阻断）。
- 无 dashboard UI、无新配置键（阈值用既有 config 派生常量，design 固化）。

## Capabilities

### New Capabilities
- `fast-track-scale-precheck`: fast-track 派发前按 tasks.md 规模分档预算；extension 末位自动 WIP 保全

### Modified Capabilities
无 requirement 级修改：preflight gate（入口存在性）与 turn-limit anchor（轮数收口）语义不变，本能力在派发预算派生处并列新增规模维度。

## Impact

- **core/fast_track_result.py**：预算/extension 派生增加规模分档输入。
- **core/pm_engine/dispatch.py**：fast-track 分支派发前加载规模预检结果（超阈降级或提额）。
- **core/agent_runner/runner.py**（或 wip_checkpoint 挂接点）：extension 末位自动保全触发。
- **tests/**：规模分档单测 + 末位自动保全触发断言。