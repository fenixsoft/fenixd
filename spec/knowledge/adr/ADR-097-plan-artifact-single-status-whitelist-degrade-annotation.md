# ADR-097：plan 产物合法终态单值白名单 + 降级事实持久化标注

date: 2026-09-16
status: accepted

## Context

planner 忘写结果文件时 exit 0 自然收工，硬门只查场景文件放行；读侧 fallback 拾到他 spec 同名残留 status='success'，白名单外被读侧丢弃后归因变 None，误导排查再降级 legacy 整轮烧钱（12min+）；降级后的框架合成报告不标注降级事实，读者无从知道报告非 agent 产出。

## Decision

- 产物硬门校验路径与读侧 primary 同源函数计算（planner 契约落点），不查 worktree 根拷贝源——planner 直接写主树绝对路径（prompt 注入值）时 worktree 根无该文件，查拷贝源会造成健康轮次误拦。
- 合法终态按 agent 类型收窄：planner-plan 只认 plan-ready 单值；judge/verifier 词汇（verified/bug-found/scenario-repaired）出现即语义错位（implementer 残留同理）。实现为独立模块常量，不复用多值白名单，防「judge 合法值替 plan 类型放行」；读侧判定口径与硬门完全一致。
- 硬门归因携带真实读到的 status 值，杜绝「读到 'success' 却报 None」式归因丢失。
- 降级上下文经落盘文件传递（reason / run_id / duration / cost / degraded_at），不走实例属性（跨阶段脆弱不持久化）也不走 STATE error 反解析（耦合文案格式）；合成报告读取注入，标注随 report.json 顶层字段持久化，渲染层头部追加一行降级说明（前端条件渲染，无标注零渲染）；新验证流程成功完成时删除旧降级文件，防陈旧标注污染后续正常报告。
- 不新增独立重试机制：产物缺失走既有产物硬门瞬态退避重试通道（零新增）。

## Consequences

- 忘写产物的 planner 轮在硬门处分钟级退避重试，替代整轮降级 legacy；重试仍失败按既有 attempt 上限走失败路径，不产生「succeeded 却无效产出」。
- 健康轮次误拦代价（分钟级退避）远小于降级代价（12min+），方向正确；模型忘写行为本裁定不治，精确归因为后续 prompt 强化或模型升级提供观测数据。
- 降级标注只在合成路径注入，agent 自写报告路径不受影响。
