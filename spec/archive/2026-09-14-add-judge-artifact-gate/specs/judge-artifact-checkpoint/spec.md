# judge-artifact-checkpoint — judge 裁决逐场景增量写盘

## ADDED Requirements

### Requirement: judge 逐场景 checkpoint
planner-judge prompt（agents/planner-judge.md）SHALL 要求：对 report.json 的增强**每归类完一个非 PASS 场景立即原子写回**（覆盖写），而非全部完成后一次性写回；步骤顺序 SHALL 为「先对全部非 PASS 场景完成最小增强落盘，再按复现预算做深入调查/复现」。

#### Scenario: 中途截断保留已归因场景
- **WHEN** judge 在归类第 N 个场景（N<总数）后遭遇流截断，本次 run 因产物硬门判失败
- **THEN** report.json 中前 N 个场景已带合法 `classification`/`evidence`（下次重试的 judge 直接沿用，只补剩余场景）

#### Scenario: prompt 明确先落盘再深入
- **WHEN** 阅读 agents/planner-judge.md 步骤段
- **THEN** 步骤 4 含逐场景写回要求，效率纪律段含「先落盘再深入」约束

### Requirement: 截断恢复沿用已有增强
prompt SHALL 注入：重试的 judge 读到的 report.json 可能含上一轮部分增强，**已带合法 `classification` 的场景 MUST 直接沿用，只对缺失/非法场景补充**——与既有违规清单注入（裁决重试 D2）正交叠加。

#### Scenario: 重试只补缺失场景
- **WHEN** 重试 judge 读到的 report.json 已有 N 个场景带合法分类、M 个缺失
- **THEN** judge 仅对 M 个缺失场景归类并写回；N 个已归因场景不被改写
