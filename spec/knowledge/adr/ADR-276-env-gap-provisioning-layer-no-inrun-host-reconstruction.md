# ADR-276：环境缺口路由环境供给层，run 内禁宿主级不可逆改造

date: 2026-10-14
status: accepted

## Context

实证事故：implementer 为使单个验证场景（模拟器相机桥）通过，在 run 内给宿主 v4l2loopback 打内核补丁、降级 emulator、换镜像，约 300+ 轮两小时全部失败后被轮数上限击杀，成本未入账；同型形态当日二连。design 已预设 fallback 条款且在开局首读上下文中，但提示词无止损硬规则、无强制力，环境问题被当作可修复问题无限深挖。

## Decision

run 内禁止为救单个验证场景对宿主做内核级/镜像级不可逆改造（内核模块替换、系统镜像降级等）。环境缺口一律路由至 env 升级或环境供给层处置；verify.yaml prepare 层的幂等宿主环境预置不受禁令约束。配套止损硬规则（提示词级强制）：同一环境依赖连续失败尝试达阈值即冻结该任务，design 有 fallback 条款先走 fallback，否则登记 unfinished 转 partial 继续其余任务；环境依赖类任务在任务书标注「环境依赖、有/无 fallback」类别供联动。

## Consequences

宿主环境稳定性不再被单个 run 挟持，run 的轮数与成本预算不再被环境深挖吞噬；场景级环境缺口以 fallback/unfinished/partial 明确落地，不再无限补救。环境准备责任收敛到供给层（prepare/预置），代价是真实需要宿主改造的场景必须走显式环境供给通道（run 外人工或环境供给 SPEC），不能在 run 内顺手完成。
