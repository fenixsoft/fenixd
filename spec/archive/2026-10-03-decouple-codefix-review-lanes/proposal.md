# 提案：decouple-codefix-review-lanes

## Why

2026-09-24 周期审查 run 发生 ocr scan 网络僵死（2h20m 仅 49s CPU），在飞期间 code-fix 车道 90 分钟未派批（15:15 延迟批合回成功后无任何派发，直到 16:42 人工取消 + 16:44 daemon 重启后 16:45 才恢复）。code-fix 吞吐被审查车道的僵死 run 绑死；且已登记的 todo（「ocr scan 僵死 agent 重试不降级」）只治审查车道自身，不治它对 code-fix 的连坐。

## What Changes

- **ADDED** 取证任务：定位 code-fix 批派发被周期审查 run 阻塞的确切机制（候选：延迟批合回路径缺自驱动推进 `_resubmit`，链激活依赖「审查 run 收尾 inserted>0」事件，僵死 run 永不收尾 → 链饿死；以代码证据定案）
- **ADDED** 派发解耦：code-fix 批派发/链推进 MUST NOT 以「周期审查 run 在飞」为否决或等待条件；与审查的真实资源冲突点（回归主机级锁）由既有锁自然串行
- **ADDED** 审查 run stall 看门狗：审查 run 无产出超阈值（进度产物 mtime + 进程 CPU 时间双判据）→ 自动取消并走既有急救/落账路径，释放车道
- 既有「审查收尾 `inserted>0` 两路激活」语义保留（正常收尾仍触发链）

## Capabilities

### New Capabilities

- `codefix-review-lane-decoupling`: code-fix 车道与周期审查 run 的调度解耦与审查僵死看门狗

### Modified Capabilities

（无）

## Impact

- `core/code_fix.py`（激活/推进路径）
- `core/agent_runner/`（run 终态/stall 判据——已有 per-run stalls 统计可复用）
- `core/admin_monitor.py` 或 `maintenance_runs.py`（审查 run 看门狗挂载点）
- `.fenix/config.template.yaml`（看门狗阈值配置键）
- 互补关系：`add-code-review-concurrency-and-429-resilience`（并发与 429 治理）、todo.md「ocr scan 僵死 agent 重试不降级」（审查车道内重试策略）——本 SPEC 不重复治理，只保证 code-fix 不被连坐 + 僵死 run 最终被收走
