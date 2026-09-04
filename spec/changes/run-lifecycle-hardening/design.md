## Context

2026-09-03 全天复盘（4 spec 完成、61 次秒挂、2.5h planner 丢弃、4 次归档未提交）暴露的四类问题，涉及调度闸门、run 超时、push 流程、对账四个子系统。相关既有机制：provider 熔断（4xx circuit，failover-dispatch）、supervision 续期（timeout_supervision）、归档联动（add-spec-archive + remove-auto-run-cleanup 的归档挂钩）、结构化冻结 frozen 字段（d4e410e）、预算对账 WARN（fix-fenix-token-waste 后续）。

## Goals / Non-Goals

**Goals**

- 归档产物随 push 闭环入库，主树不再留 openspec 残留
- 秒挂风暴从 61 连发降为「3 次 → 冷却 5 分钟 → 自动恢复」
- run 超时按 agent_type 粒度可覆盖，planner 类显著短于 implementer，全局单源默认保持
- 三项卫生修复（verifier 链尊重 frozen、STATE 路径唯一、对账自动校正）

**Non-Goals**

- 不改 provider 熔断（4xx circuit）语义
- 不实现 dispute 申诉通道（独立 SPEC）
- 不做 todo/自省类功能（另见 add-daily-self-review）
- 不引入新的守护进程/定时器——秒挂冷却与归档提交均挂在既有调度与 push 路径上

## Decisions

**D1 归档提交挂在 push 流程尾部（而非归档动作发生时立即提交）**：归档动作可能批量发生（一天多次），逐次提交会打断 push 语义且与 spec_done 的 push 竞争；push 尾部一次性收口当天全部残留，冲突时 WARNING 留给下次重试，不阻塞 spec 终态。

**D2 秒挂判定以「进程存活时长」为准，不解析退出码**：Exit 143/137/1 等码在不同环境语义不稳（SIGTERM 也可能是被 supervisor 正常终止），存活 < 阈值秒即视为瞬时死亡更稳健；「被框架主动 SIGTERM 的 run」不计入（liveness/shutdown 路径已有标记）。

**D3 timeout_overrides 白名单校验**：键必须是 KNOWN_AGENT_TYPES 成员 + `supervision-judge`；值必须为 ≥300 的整数。非法键值整条忽略并打 ERROR（不部分生效），避免配置笔误造成半生效状态。stuck 阈值与派生链保持全局默认值语义（D4）。

**D4 stuck 阈值不随覆盖联动**：stuck 是「调度层面无进展」信号，应与全局超时同源；若随各类型覆盖漂移会让 admin 巡检阈值随配置抖动。仅在 spec 场景锁定该语义。

**D5 对账校正只在「无豁免因素」时执行**：保留上限/死亡豁免导致的偏差沿用既有 WARN（自动改数会破坏豁免语义）；纯漂移（无豁免因素且 runs 数可复算）才自动改写 used。

**D6 verifier 链冻结检查点放在「每次 attempt 启动前」**：与 implementer 链的 `_should_give_up_before_retry` 同构，复用 frozen 字段读取，不新增状态。

## Risks / Trade-offs

- 归档提交与用户手工操作主树并发 → 用 `git add` 限定 openspec/changes 路径（不 `add -A`）；提交失败降级 WARNING 不阻塞
- timeout_overrides 配置过短会截断正常长 run → 护栏下限 300s + ERROR 告警；默认无 overrides 时零行为变化
- 秒挂冷却可能延迟正常重试 5 分钟 → 冷却仅在「连续 3 次秒挂」后触发，正常单次瞬时失败不受影响

## Migration Plan

纯增量：新配置键缺省缺席 → 全部行为回退现状。唯一删除项 `.fenix/STATE.md` 是 0 字节遗留文件，无消费方。

## Open Questions

- 无。
