<!-- knowledge: capability=judge-artifact-checkpoint rev=1 sources=spec/archive/2026-09-14-add-judge-artifact-gate -->

# judge 产物检查点

planner-judge 对 report.json 的逐场景增量写盘纪律：流截断时已归因场景不丢失，重试只补缺失场景。

## 现行规则

- planner-judge prompt 要求对 report.json 的增强逐场景 checkpoint：每归类完一个非 PASS 场景立即原子写回（覆盖写），而非全部完成后一次性写回。
- 步骤顺序为「先对全部非 PASS 场景完成最小增强落盘，再按复现预算做深入调查/复现」（先落盘再深入），效率纪律段含该约束。
- judge 在归类中途遭遇流截断时，本次 run 因产物硬门判失败，但 report.json 中已完成归类的场景已带合法 `classification`/`evidence`。
- 重试的 judge 读到的 report.json 可能含上一轮部分增强：已带合法 `classification` 的场景 MUST 直接沿用，只对缺失/非法场景补充归类并写回；该沿用规则与既有违规清单注入（裁决重试 D2）正交叠加。

## 溯源

- [2026-09-14 add-judge-artifact-gate](spec/archive/2026-09-14-add-judge-artifact-gate/) — 确立 judge 逐场景原子写回 checkpoint、「先落盘再深入」步骤顺序与重试沿用已有增强的注入契约
