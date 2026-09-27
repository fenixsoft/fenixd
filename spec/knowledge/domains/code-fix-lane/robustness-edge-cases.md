# 边界场景健壮性修复批

<!-- knowledge: capability=robustness-edge-cases rev=1
     sources=spec/archive/2026-09-21-fix-robustness-edge-cases -->

run 流归属、告警存储与结构化日志三类边界健壮性的现行规则。

## 规则

### run 流归属全等匹配
- 所有按 spec 名查找 run 流文件的判定点必须使用完整 spec 名全等比较，不得仅凭 `glob(f"{prefix}-{spec_name}-*.jsonl")` 命中即认定归属；实现复用单一来源解析器（`run_spec_part`），对每个 glob 候选解析出完整 spec 名后再比较。
- 解析器必须能正确解析全部既有 run 产物命名形态，含 attempt 后缀（`-a<n>`）与瞬态重试后缀（`-r<n>`）；形态被漏解析的假阴性危害等价于误命中——活性判定取假会误报 stuck 并触发误杀、预算豁免失效、任务进度与 planner 耗时取到旧产物。
- 前缀命中的他 spec 流必须排除（`impl-fix-x-y-<ts>.jsonl` 不计为 `fix-x` 的流）；后缀形态必须命中（`impl-fix-x-<ts>-a1.jsonl`、`impl-fix-x-<ts>-a1-r2.jsonl` 均归属 `fix-x`）。
- 判定点全覆盖：worktree 残留判定、活性判定、recent-run-activity、预算豁免判定、任务进度、planner 耗时等处均须全等匹配（任一遗漏即不合规）；形态更宽的同类点（如子串 glob）必须给出显式处置结论（纳入或书面 defer 并注明承接方）。

### 告警存储读损坏防护
- `AdminStore` 读取告警文件遇到解析失败时，先把损坏文件改名留底（形如 `.corrupt-<时间戳>`），再返回空集合，并产生一条可观测记录。
- 任何「读-改-写」回写前必须校验记录数下限：本次写入会导致既有历史整体丢失时拒绝写回并记录告警。
- 损坏留底后新增告警正常写入新文件，不得因下限保护被拦（留底已保留历史取证）；文件不存在或内容为合法空数组时写入不被误拦；正常追加保留既有记录。

### 结构化日志收敛
- 除 `fenixd` 层级（可传播到已挂载的 handler）或显式注入的 Logger 实例外，代码不得使用裸 `logging.getLogger(...)` 记录运行时告警/错误；所有运行时 WARNING/ERROR 必须落入结构化日志文件（`fenixd.log`）。
- 防回归静态检查必须覆盖全部裸 `getLogger` 点（不得只按白名单文件名枚举），新引入的裸 `getLogger(...)` 会被检出。

## 溯源

- 2026-09-21 2026-09-21-fix-robustness-edge-cases — 新建本页：run 流归属全等匹配（七处判定点收敛、后缀形态不漏命中）、告警存储损坏留底与清库式写回拒绝、裸 getLogger 旁路收敛与静态防回归。
