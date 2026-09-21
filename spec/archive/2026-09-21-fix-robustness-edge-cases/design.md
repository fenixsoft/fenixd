# Design: fix-robustness-edge-cases

## Context

三处可复现缺陷：spec 名互为前缀致 run 流误归属（仅 recovery.py 一处补了守卫，其余 6 处未补）；`admin_alerts.json` 读损坏静默清库；旁路 logger 致 WARNING/ERROR 不进结构化日志。修复范式仓库内均已有先例。

## Goals / Non-Goals

**Goals**：消灭误归属与静默丢失；统一到既有范式（`run_spec_part` 全等匹配、留底后返回空、可传播 logger）。

**Non-Goals**：不重构 logger 体系；不改告警检测规则。

## Decisions

### D1：归属判定统一走 `run_spec_part`（**前置：先补齐其对 `-r<n>` 的解析**）
`recovery.py` 已示范：glob 命中后逐候选 `run_spec_part(p.stem) != spec_name → continue`。本变更把七处同型点改为同一写法，`run_files.RUN_ID_AGENT_PREFIXES` 为唯一前缀真源。

**前置修复（MUST，否则本变更净效果为负）**：现状 `run_spec_part`（`core/agent_runner/run_files.py:66-77`）先 `re.sub(r"-a\d+$", "")` 再剥时间戳，**不识别瞬态重试后缀 `-r<n>`**。实测 `.fenix/runs/` 中已有 **40 个** `<prefix>-<spec>-<ts>-a<n>-r<m>.jsonl` 形态文件（如 `impl-add-control-plane-silent-failure-guards-1789419431-a1-r1.jsonl`），对这些文件 `run_spec_part` 返回整段 `add-control-plane-silent-failure-guards-1789419431-a1-r1` 而非 spec 名。若直接以「全等守卫」替换前缀 glob，这些**在跑的** run 会被判为「非本 spec」：活性/近期活动判定取假、预算豁免失效、`find_impl_run_file` 回退到旧产物、planner 耗时取错文件——即把「前缀误命中」换成「真实 run 漏命中」，而后者会误报 stuck 并触发误杀。

仓库内已有更强解析器与前次事故记录：`core/admin_monitor.py:1856` `_spec_from_run_id` 用 `^(.*)-\d{9,10}(-(?:a|r)\d+)*$`，其 docstring 明载「若漏剥 `-r<n>` 将解析失败返回 None，导致 `_has_recent_progress` 匹配不到活跃 run 而误报 stuck（evo-verifier-result-single-source 事故实证）」。`-r<n>` 由 `core/agent_runner/runner.py:2703/2712` 生成。

因此本变更 MUST 先把 `run_spec_part` 的后缀剥离补全为同时处理 `-a<n>` 与 `-r<n>`（保持 `RUN_ID_AGENT_PREFIXES` 为**前缀**唯一真源），再在全仓以其为唯一归属判据，并补 `<spec>-<ts>-a1-r2` 形态的回归用例（见 tasks 1.0/1.3）。
**替代**：改文件名分隔符——否决，影响全部历史 run 文件与消费点；直接改调 `_spec_from_run_id`——否决，前缀真源会分裂为两份，与该模块「前缀表唯一真源」注释相悖。

### D2：admin_store 损坏留底 + 写回下限保护
读失败先把文件改名 `.corrupt-<ts>` 再返回 `[]`（保留取证），写回前若「旧记录整体丢失」则拒绝。**关键**：读-改-写是持锁原子序列，只改读侧不够，必须同时守住写回。

**判据必须可判定（MUST）**：留底改名后 `_read_unlocked` 返回的 `[]` 与「文件本不存在 / 合法清空」在返回值上**不可区分**（`core/admin_store.py:70-75`），故「旧记录整体丢失」不能以实现默认语义推断，否则二选一皆错：或恒不触发（死代码，静默清库仍在），或拦掉损坏后的合法恢复写入（告警从此写不进）。实现 MUST 让 `_read_unlocked` 以显式信号（返回值或 `_mutate` 内的标志）区分「本次读取因损坏走了留底路径」，下限保护**仅在该信号为真时**拒绝写回；正常空文件/合法清空路径 MUST NOT 被拦。对应用例见 tasks 2.3 的「损坏后恢复写入」场景。

### D3：logger 收敛 + 级别判定修复
运行期告警改为 `fenixd.` 层级或注入 Logger；同时修 `logger.py` 的 `handle(record)` 绕过 `isEnabledFor` 的问题，使 `logging.level` 生效（DEBUG 不再恒落盘）。
**替代**：给 root logger 挂 handler——否决，会收编所有第三方库日志。

## Risks / Trade-offs

- [全等匹配改动波及活性/残留判定，误伤正常路径] → 每处改动配前缀对照用例（`fix-x` vs `fix-x-y`），并配后缀形态用例（`-a1` / `-a1-r2`）。
- [补齐 `-r<n>` 解析后，历史 40 个 `-a<n>-r<m>` 文件的归属由「伪 spec 键」改归真实 spec] → 波及 `core/dashboard/data.py:2930 _runs_by_spec_sigs` 分组与 `get_runs` 索引及时间轴归属；此为修正而非破坏，但验收须跑 `tests/test_dashboard_*` 确认全绿。
- [admin_store 写回下限保护误拦合法清空] → 仅在「旧记录全丢且本次新增 >0」时拒绝；显式清空操作不走该路径。
- [logger 层级变更致消息重复] → 断言 handler 数量与传播路径唯一。

## Migration Plan

三块各自独立 commit（归属匹配 → admin_store → logger），每块跑全量 pytest。**回滚**：逐块回退。
