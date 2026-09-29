# 无结论重验并行降档
<!-- knowledge: capability=inconclusive-parallel-backoff rev=1 sources=spec/archive/2026-09-17-add-verify-parallel-backoff -->

全批 blocked-env（inconclusive）重验时按连续 attempt 自适应下调验证并行度，避免同一资源过载条件下原样重复空跑。

## 现行规则

- 递减规则：`_handle_env_blocked_inconclusive` 判定全批 blocked-env 且 attempt 未超上限时，按连续 blocked-env attempt 数计算降档并行度写入 spec attrs 的 `_verify_parallel_override`，下一轮 `VerifyEngine` 以该值覆盖 `max_parallel` 配置值。有效并行度 = `max(1, 配置值 >> (attempt - 1))`（逐 attempt 减半向下取整，下限 1；如 5→2→1）。
- 首次不降档：attempt 1（首次重验判定）不写入 `_verify_parallel_override`——首轮白屏证据尚不存在，降档会冤枉健康环境。
- 健康轮自动复位：任一轮验证结果非 inconclusive（出现 verified / bug-found 等正常判定，或有效失败 failed+errors>0）时清除 `_verify_parallel_override`，恢复配置并行度；`_inconclusive_attempts` 的既有清零点（人工解冻 unfreeze、fast-track verified）同步清该字段。
- 降档可观测：降档生效轮在引擎启动日志与 report.json 透出有效并行度及降档来源（如「并行度=2（inconclusive 降档）」、report 顶层 `effective_parallel=2`）；非降档轮不出现降档标记。

## 溯源

- [2026-09-17 add-verify-parallel-backoff](spec/archive/2026-09-17-add-verify-parallel-backoff/) — 新增 inconclusive 重验并行度按 attempt 递减、健康轮自动复位与降档可观测（此前重验并行度不变，被测实例渲染过载时同一条件原样复现连续空跑）
