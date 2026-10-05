# code-fix 批 API 超时签名判别与失败现场抢救

<!-- knowledge: capability=code-fix-api-timeout-salvage rev=1
     sources=spec/archive/2026-10-06-evo-code-fix-api-timeout-salvage -->

code-fix 批 run 死于单轮 API 请求超时时的签名判别与现场抢救：把「一次超长请求超时即死」从压扁的异常字符串升级为结构化签名，在失败判定当时就把 WIP 提交保全并登记复用，让同链下一批从 salvaged 工作起步，避免整批 40+ 分钟级工作随陈旧清扫悬空蒸发。

## 规则

### API 超时签名判别（runner 层单源）
- 判别点固定在 agent runner 层（`_run_claude` 非 0 退出分支，失败异常已携带 stderr/has_result/exit_code）一次完成，车道层只读标记，编排层不得重新解析归档做二次判别。
- 命中条件（两形态任一）：CLI Exit 1 且末次 result 事件 `terminal_reason == "api_error"`；或 result 文本命中 CLI 合成的 "Request timed out" 超时文本。
- 判别结果以布尔标记 `api_timeout` 挂在失败异常上，并随 `run_code_fix` 失败信封结构化透出（附 `exit_code` 与 stderr 尾行摘要）；失败记录与日志的 error 文本携带 `api_timeout=True/False` 与退出码留痕，不再把签名压扁为异常字符串。
- 非超时失败（确定性异常、turn_limit、成功终局、空 result，以及超时文本仅出现在 stderr 字段未扩散到 result）一律判 `api_timeout=False`，不得误标。

### 失败现场抢救（挂在失败当时）
- `api_timeout` 终局且 worktree 工作区存在未提交改动时，判失败的编排分支 MUST 先抢救再清理：复用既有 `_salvage_commit` 把 WIP 以 salvage 提交落到该批分支（不新增提交机制），随后按既有清理路径登记 recovery legacy（宽限期内豁免陈旧清扫），并对批建树 spec_name（`code-review-fix`）置 `mark_legacy_reusable` 复用标记。
- 抢救挂点在失败判定的当时，不是陈旧清扫期——清扫期的快照注定悬空（彼时消化链已推进多批、无读者承接）。Pre-rmtree 快照机制保留为最后防线，语义不变。
- 工作区干净（无未提交改动）时跳过 salvage：不产生 salvage 提交、跳过行为写日志留痕，cleanup 照常执行；recovery legacy 照常登记但不置复用标记，下一批全新建树。
- salvage 不改变条目核销状态：失败批条目保持 `open`，重试批可能重复修同一条目的成本由台账核销去重兜住。

### 同链下一批接续 salvaged 现场
- 接续只走既有 reuse 认领通路：同链下一批建树时 `wm.create` 经 `_take_reusable_worktree` 认领置了复用标记的 legacy，继承 salvaged 分支（仅分支模式在既有分支上重建载体，MUST NOT 从 main HEAD 起新分支），salvaged 提交对重试批可见；认领即把该 legacy 摘出登记表。
- 认领不可用（无 legacy / 载体失效 / 换壳失败）时 MUST fail-open 降级为现状行为——全新建树落新分支，不阻断链推进，无效 legacy 一并清除，不出现车道死锁。
- MUST NOT 用 `consume_legacy` 实现接续：其语义是「后继成功 merge 后回收」（出册 + 强删 worktree + 删分支），建树前调用会删掉承载 salvaged 提交的分支，复刻悬空提交净损失。

### 边界保形（非超时失败行为不变）
- 非 `api_timeout` 的失败即使工作区脏也不做 salvage：立即清理，条目按既有语义处置——agent run 层失败入 `chain_skipped` 跳批推进、确定性失败入失败档案烧跨链重试预算（见 [code-fix 批失败自愈](code-fix-batch-selfheal.md)）。
- 「失败 = `chain_skipped` 跳批推进」的链语义与确定性失败重试预算语义不因 salvage 改变；salvage 只改变清理时序与现场去向，链在失败批后继续推进不 halt。
- run 停滞判停预算（`run_stall_budget`）缺省关闭维持不变，API 超时终局不纳入停滞判停判据（单轮超时无论如何终止于该轮，纳入判停不减少损失）；spec 车道的原位瞬态重试通路与本能力互不相干。

## 溯源

- 2026-10-06 2026-10-06-evo-code-fix-api-timeout-salvage（spec/archive/2026-10-06-evo-code-fix-api-timeout-salvage） — 新建本页：API 超时签名 runner 层结构化判别与失败信封透出、失败当时 WIP salvage 提交批分支 + recovery legacy 保全 + 复用标记、同链下一批 reuse 认领接续（认领 fail-open、禁 consume_legacy 接续）、非超时失败与链跳批语义保形。
