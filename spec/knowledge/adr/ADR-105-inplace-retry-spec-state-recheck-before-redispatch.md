# ADR-105：原地重试重派前复查 spec 状态与冻结 / 取消

date: 2026-09-17
status: accepted

## Context

attempt 内的原地重试子循环（provider 瞬断、产物硬门通道）在退避 sleep 后直接 continue 重派，期间 spec 状态可能已被 admin / 人工改为 blocked / frozen——重试轮与人工接管竞跑白烧（实证单轮 $4.77）。attempt 层已有「放弃重试」检查先例，子循环层缺同款。

## Decision

- 原地重试子循环在退避后、重派前必须复查：spec 当前状态是否仍为本 agent 的预期态（judge=testing、implementer=implementing），且无人工冻结与取消旗标；非预期态 → 放弃重试并返回语义化失败，不静默重派。
- 复查与 attempt 层既有 give-up 检查同源扩展（helper 就地增加 status 判定，不另起新方法名），防两套判据漂移。
- 复查自身异常 fail-open（维持既有重试语义）：极窄的竞态窗口接受，正确性与重试可用性取平衡点在可用性。

## Consequences

- 人工接管 / 冻结后不再被在飞重试踩踏；重试预算只花在仍被期待的 run 上，放弃路径留语义化失败记录供审计。
- 一切原地重试通道（瞬断退避、产物硬门、重合成等）接入此复查为标配。
