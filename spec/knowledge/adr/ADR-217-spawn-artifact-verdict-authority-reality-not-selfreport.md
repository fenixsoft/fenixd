# ADR-217：spawn 产物成败判定权威是产物实况而非 agent 自述，形态校验尽力而为

date: 2026-10-04
status: accepted

## Context

daemon spawn headless claude 产出文件产物的功能（回归草稿 autodraft、项目架构图 archify）都需要回答「这次生成算不算成功」。claude 进程的 stdout 自述不可信：可能声称完成而产物缺失、为空或形态无效；若以自述或退出码单点判定，会把无效产物洗成 ready。

## Decision

spawn 型产物的成败判定权威固定为机械证据链，按序校验：进程退出码 → 产物文件存在且非空 → 产物特征校验（如自包含 HTML 的起始 `<html` / `<!DOCTYPE html` 特征）→ 结构化 marker 提取（stdout 末行 marker 携带结构化结果，如组件数；marker 缺失时从产物本身提取）。任一必需环节不满足即判 failed，不采信 agent 自述。

形态类数值校验（如组件数 ∈ [8,16]）只对「能提取到」的情况生效：提取失败时不硬判 failed，记 null 并放行——产物可用性优先于校验完备性。范围校验是「能提取才校验」，不是「提取不到也算违规」。

## Consequences

- spawn 型功能的成败判定无歧义且可单测：fake Popen 按环驱动权威链即可覆盖全部失败路径，无需真实 claude。
- 形态契约在实现上是「尽力而为」：产物可用但 marker 缺失时放行，验收与评审方不得以「形态校验未拦截」判缺陷。
- 后续任何「spawn 产出产物」的 SPEC 沿用同一权威链，不得引入「信任 agent 自述」的捷径；新增结构化判定需求走 marker 协议扩展，不另起判定通道。
