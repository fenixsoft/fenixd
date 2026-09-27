# ADR-084：产物契约型 agent 成功判定加产物硬门，两类重试预算分离

date: 2026-09-14
status: accepted

## Context

全部 agent run 以进程退出码判成功：网关流截断可使最后一条消息句中截断但 `stop_reason=end_turn`、CLI exit 0——judge 产物（report.json 增强、结果文件）实际缺失。缺失在下游校验才被发现，且被误计入「产物不合规 → 重试一次 → blocked」的裁决预算，假成功烧穿预算后转 blocked。下游前置检查的替代方案会把产物缺失算进裁决预算且丢失 provider 瞬态分类信息，归因晚一层。

## Decision

- 有明确产物契约的 agent 类型（`planner-judge`/`planner-plan` 白名单）在 run 成功判定处（`_execute_agent`）加产物硬门：exit 0 后校验结果文件存在且 JSON 可解析（解析失败视为缺失），缺失判 `success=False`，error 注明产物硬门，失败落入 provider 瞬态重试通道原样复用（不新增重试机制）。
- 结果文件路径与 prompt 注入的 `{result_path}` 同源计算（路径计算函数从 prompt_builder 抽取共用），禁止双实现漂移。
- 两类预算分离：产物缺失 = run 级失败（provider 瞬态重试）；产物存在但不合规 = 裁决级失败（重试一次 → blocked，既有语义不动）。
- judge 逐场景 checkpoint：每归类一个非 PASS 场景立即原子写回 report.json（temp+rename 覆盖写），先全部落盘再深入调查；重试轮沿用已带 classification 的场景只补缺失场景（截断恢复语义）。结果文件保持最后一步写入——截断发生在其前即 run 判失败重试。

## Consequences

- 「exit 0 但产物缺失」fail-closed 进瞬态重试，judge 失败归因提前一层并保留 provider 分类信息；白名单外 agent 不受影响。
- 逐场景 checkpoint 使截断重试保留已归因成果，重试成本下降；写回为单文件小 diff，输出 token 增量可控。
- 不做网关流截断的通用检测（启发式误判率高），产物硬门以确定性可解析性为界。
