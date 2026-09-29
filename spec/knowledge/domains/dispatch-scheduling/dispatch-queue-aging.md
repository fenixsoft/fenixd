<!-- knowledge: capability=dispatch-queue-aging rev=1 sources=spec/archive/2026-09-02-improve-scheduling-noise-governance -->

# 派发队列老化治理

队列条目按等待时长获得等效提级，使被持续高优任务压制的低优先级条目仍能获得派发窗口，防止饿死。

## 现行规则

- 队列每个条目记录入队时间戳；参与优先级判定用有效档位 `effective = max(0, base − aging_bonus)`，其中 `aging_bonus = min(floor_levels, max(0, floor((elapsed − initial_wait) / step_down)))`。priority 数值越小越优先，因此等待越久比较档位越高。
- 配置键 `pm.dispatch.aging.enabled / initial_wait_minutes / step_down_minutes / floor_levels`，缺省 `enabled=false`（关闭时恒不老化，行为与未老化完全一致）、`initial_wait_minutes=30`（零窗口）、`step_down_minutes=15`（每满一档时间等效提一级）、`floor_levels=4`（等效提级总量上限，如 P6 最低可比至 P2，仍天然低于新到的 P1，高优家族先占）。
- 等待时间不足 `initial_wait` 时 `effective == base`，判定结果与未老化一致。
- 老化边界约束：
  - 活跃运行中的任务不参与老化——活动集合记 base 原值，不影响活跃优先级判定语义；
  - 单条目等效提级总量以 `floor_levels` 为上限；
  - 老化仅内存态，daemon 重启后重建的队列从零计时；
  - 同级（effective 相等）条目间相对顺序保持稳定：先入队先派发，不被老化扰动（队首条目老化收益 ≥ 后入队者，队首扫描天然保持同级 FCFS）。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：派发队列按 effective_priority 有限等待窗口老化，等待超窗后提级，防低优先级饿死
- [2026-09-02 2026-09-02-improve-scheduling-noise-governance](spec/archive/2026-09-02-improve-scheduling-noise-governance/) — 固化入队时间戳、老化公式与边界约束（活跃任务不老化、floor 上限、同级顺序稳定），配置键 `pm.dispatch.aging.*` 缺省关闭保持向后兼容。
