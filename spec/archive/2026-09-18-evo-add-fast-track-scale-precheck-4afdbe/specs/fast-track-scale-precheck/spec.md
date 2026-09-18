# fast-track-scale-precheck 增量规格

## ADDED Requirements

### Requirement: 派发前规模分档
fast-track 派发前 MUST 依据 spec 的 tasks.md 任务条数（及 spec 目录文件面）做轻度静态规模预估，并按设计固化阈值分档：预估超阈时 MUST 自动降级为 full 模式或按高一档 extension 预算派发，不得再按统一 3.5h 硬限处理。预估失败（tasks.md 缺失等）MUST 保守按低档放行并记 WARNING，不因预检失败阻断派发。

#### Scenario: 大任务面 spec 首次派发即获更高预算
- **WHEN** spec 的 tasks.md 任务条数/文件面超过设计阈值，且首次以 fast-track 派发
- **THEN** 自动按 higher-tier 预算（或降级 full 模式）派发，不再进入 3.5h 统一档

#### Scenario: 小 spec 行为零变化
- **WHEN** spec 规模低于阈值
- **THEN** 按既有 fast-track 预算原样派发

#### Scenario: 预检输入缺失保守放行
- **WHEN** tasks.md 缺失或读取失败导致无法预估
- **THEN** 按低档放行并记 WARNING，不阻断派发

### Requirement: extension 末位自动 WIP 保全
fast-track 超时预算进入末尾（extension 用尽前，具体提前量由 design 固化）时，MUST 在终止收口前自动触发一次 WIP checkpoint 保全，复用既有 `commit_wip_checkpoint`（失败降级不阻断，消息契约 `fenix(wip): checkpoint extension-tail <spec>`）。已完成的轮次工作不得随超时无保全作废。

#### Scenario: extension 末位触发保全
- **WHEN** fast-track run 进入 extension 末位窗口仍无收尾成果
- **THEN** 自动执行一次 WIP checkpoint 提交，含全部未提交产物，随后按既有超时路径收口

#### Scenario: 保全失败不阻断收口
- **WHEN** 末位保全的 git 操作失败（超时/权限）
- **THEN** 仅 WARNING 留痕，既有超时收口照常执行