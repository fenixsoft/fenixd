# testing 跃迁即时派发

<!-- knowledge: capability=testing-dispatch-liveness rev=1
     sources=spec/changes/add-adjudication-auto-exec -->

外部进程直写 STATE 使 SPEC 进入 testing 态后的 verifier 即时派发通道：watch 通道秒级补位，消除「等 30 分钟周期 full_scan 兜底」的派发真空（典型场景=告警裁决外写解冻进 testing）。

## 规则

- testing 态跃迁不产生 PM 事件（`_status_to_event` 返回空）：dashboard 等外部进程直写 STATE 解冻进入 testing 后，事件通道对 verifier 派发无感知，只能等 30 分钟周期 full_scan 的 `_recover_testing` 兜底。
- watch 通道（秒级 checksum 轮询）补齐该跃迁的即时派发：`_diff_specs` 在锁内采集「既有 SPEC 跃迁进入 testing」——新出现的 SPEC 直接呈 testing 态不采集（防基线重建窗口的派发风暴）；`_dispatch_changes` 锁外对命中件复用 `_recover_testing` 等价 re-trigger 逻辑即时派发 verifier。
- 复用既有恢复路径与判定语义，零新增 PM 事件类型：无驱动判定（`spec_is_undriven`）、在飞 Administrator run 互斥与队列去重全沿用——已有在飞 run 或排队条目的 testing 跃迁不重复派发，状态维持原样等在飞 run 自然推进；即时通道 MUST NOT 绕过或破坏既有互斥检查。
- 派发失败（引擎瞬时不可用等）单条 WARNING 隔离：无状态损坏、无重复 run 残留，下一轮 30 分钟 full_scan 扫到无驱动 testing 态后补派发——watch 即时通道与 60 秒 ready 精触发、30 分钟 full_scan 兜底三层共存互为重试网。

## 代码锚点

- 主实现：`core/event_bus.py`（`_diff_specs` 锁内采集 →testing 跃迁、`_dispatch_changes` 锁外即时派发、`_recover_testing` 复用出口）
- 守卫测试：`tests/test_event_bus_testing_dispatch.py`

## 溯源

- 2026-11-11 add-adjudication-auto-exec（spec/changes/add-adjudication-auto-exec/） — 新增本页：watch 通道补 testing 跃迁即时派发（复用 _recover_testing 恢复路径、零新增事件类型、无驱动判定与在飞互斥吸收幂等），与 60 秒精触发/30 分钟 full_scan 兜底共存
