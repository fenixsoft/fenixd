# 无结论重验并行降档
<!-- knowledge: capability=inconclusive-parallel-backoff rev=2 sources=spec/archive/2026-09-17-add-verify-parallel-backoff,spec/archive/2026-10-09-evo-fix-verify-parallel-override-type -->

全批 blocked-env（inconclusive）重验时按连续 attempt 自适应下调验证并行度，避免同一资源过载条件下原样重复空跑；降档载体 `_verify_parallel_override` 有固定类型契约（int|None）。

## 现行规则

- 递减规则：`_handle_env_blocked_inconclusive` 判定全批 blocked-env 且 attempt 未超上限时，按连续 blocked-env attempt 数计算降档并行度写入 spec attrs 的 `_verify_parallel_override`，下一轮 `VerifyEngine` 以该值覆盖 `max_parallel` 配置值。有效并行度 = `max(1, 配置值 >> (attempt - 1))`（逐 attempt 减半向下取整，下限 1；如 5→2→1）。
- 首次不降档：attempt 1（首次重验判定）不写入 `_verify_parallel_override`——首轮白屏证据尚不存在，降档会冤枉健康环境。
- 健康轮自动复位：任一轮验证结果非 inconclusive（出现 verified / bug-found 等正常判定，或有效失败 failed+errors>0）时清除 `_verify_parallel_override`，恢复配置并行度；`_inconclusive_attempts` 的既有清零点（人工解冻 unfreeze、fast-track verified）同步清该字段。
- 降档可观测：降档生效轮在引擎启动日志与 report.json 透出有效并行度及降档来源（如「并行度=2（inconclusive 降档）」、report 顶层 `effective_parallel=2`）；非降档轮不出现降档标记。
- 类型契约：`_verify_parallel_override` 只接受 int（降档并行度）或 null（复位）。人工处置复位点（reset_verification、continue_auto_fix 共用的重试计数器清零集、unfreeze 等）一律写 null，不写布尔值；布尔形状落 STATE.md 会往返字符串化、读端解析失败。
- 写侧形状守卫：update_spec 写入侧对该字段设单字段形状守卫——布尔或非 int 形状（'False'/'true' 等字符串、float）拒绝写入并告警留痕，不静默序列化进 STATE.md；只剥该字段，同批其余更新照常应用；拒绝优先于静默归 null（归一过宽会掩盖真实坏值）。
- 解析侧归一：STATE.md 解析对该字段登记 int|None 归一（null 兼容）——存量字符串化坏值（'False'、带或不带引号的 true 等不可解析形状）首读即清洗为 null 且幂等；int 字面量往返读回 int 类型。
- 读端降档与留痕：字段非 null 时覆盖 max_parallel 配置值；遇到不可解析的覆盖值时降档沿用配置并行度，告警含值 repr 形态与字段来源（取自 spec attrs），不把布尔语义映射为特定并行度（int(False)=0 会把并行度置 0，同为坏值）。

## 溯源

- 2026-09-17 add-verify-parallel-backoff（spec/archive/2026-09-17-add-verify-parallel-backoff） — 新增 inconclusive 重验并行度按 attempt 递减、健康轮自动复位与降档可观测（此前重验并行度不变，被测实例渲染过载时同一条件原样复现连续空跑）
- 2026-10-09 evo-fix-verify-parallel-override-type（spec/archive/2026-10-09-evo-fix-verify-parallel-override-type） — 新增降档覆盖字段类型契约：字段只接受 int|None，人工处置复位写 null（取代布尔 False 写法），写侧单字段形状守卫拒绝布尔/字符串/浮点形状且只剥违规字段，解析侧 int|None 归一清洗存量字符串化坏值，读端解析失败告警补字段来源留痕并禁止布尔→并行度映射
