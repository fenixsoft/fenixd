# code-fix 批内并行处置

<!-- knowledge: capability=code-fix-batch-parallel rev=4
     sources=spec/archive/2026-09-29-add-codefix-batch-parallel,spec/archive/2026-10-03-add-codefix-commit-first-contract,spec/archive/2026-10-04-add-codefix-affinity-batching -->

code-fix 批内多文件组时的并行修复协议：主 agent 以 orchestrator 身份派 Task 子代理并发处置各组，汇总落盘、统一验证提交；框架契约（单 run / 单 out_path / 回归+合回）保持不变。

## 规则

### 触发与退化
- 批分组后判定处置模式：文件组数 ≥2 且总条目 >2 → MUST 走并行处置，以文件组为粒度派子代理；仅 1 个文件组或总条目 ≤2 → 按串行路径由主 agent 直接处置，MUST NOT 为小批派子代理（调度开销大于收益）。
- 分组沿用按 `file` 分组规则，组间文件互斥（同一条目的 file 唯一 → 组间无编辑交集）；跨组共享文件的场景与串行处理风险一致，不新增处理。

### 派发（波次语义）
- 每组一个子代理；同波在飞子代理数 ≤ 框架按本批文件组数分档注入的上限（分档数值与硬上限由选批/波次能力页单源定义，见 [codefix-affinity-batching](codefix-affinity-batching.md)「批内并行波次上限自适应」），防网关限流放大。
- 同波全部子代理调用必须在同一条消息内发出（一条消息多个 Task 调用 = 真并发）；首波 MUST 一次打满在飞额度，MUST NOT 拆成多条消息逐个派发。
- 每有一组完成落盘，立即补派下一组，直至全部组派完。
- 子代理 prompt MUST 内联：该组条目 JSON；修复契约（最小改动、只处理本组条目、取证一次到位、`fenix-ignore` 忽略标记规则、out 行格式与 `item_id` 一致性纪律）；边界三禁——子代理 MUST NOT 自行写 `{out_path}`、MUST NOT 自行验证、MUST NOT 自行提交（含任何 git 写操作），只把修复改动落 worktree 文件并结构化返回每条目一行结果记录。

### 单写者落盘
- `{out_path}` 的唯一写者是 orchestrator：每组子代理返回后 MUST 立即校验返回记录（每行含 `item_id` 且属于本批清单、`status` ∈ fixed/skipped），随后把该组全部结果行以 append 一次写入并 flush；MUST NOT 攒到全部组完成才写。
- 串行路径组（退化批与兜底重做组）同样即时落盘，规则一致。
- 结果行随组增量落盘，条级进度合成（item_done/current_item）在 run 在飞期间即可读到已完成组，读侧零改动兼容。

### 失败兜底（三级）
- 子代理报错/超时/返回不可解析 → orchestrator 亲自按串行路径重做该组，照常落行。
- 重做仍失败 → 该组条目按既有 skipped 语义标注（unfixable/needs_human）。
- 返回记录非法（缺 `item_id`/`status`）→ 该组重试一次处置；重试后仍非法的条目标注 `skipped: unfixable`，MUST NOT 把非法行写入 `{out_path}`。
- 任何单组兜底 MUST NOT 阻塞其他组的落盘与派发。

### 提交与验证（边修复边提交、收尾一次验证）
- 并行只改变「谁修复、结果何时可见」，框架回归 + 合回流程与串行批完全一致：每组改动落盘后 orchestrator 把该组修复改动 commit 到当前分支（逐组提交或收尾一次提交均合法），提交 MUST 先于收尾验证完成；带未提交改动收工会触发编排 salvage 兜底，真零改动整批按 `no_effective_fix` 拒合回。
- 验证 MUST NOT 作为提交的前置条件：全部组落盘完成后按触碰面做**一次**定向验证（仅前端 → tsc + 前端单测；仅 Python → 定向 pytest；混合 → 两者），验证于提交之后进行、结果用于回归门前的自查补修（补修改动 MUST 再次 commit）；MUST NOT 逐组验证。
- 回合结束前 worktree 工作区必须干净（全部改动已 commit，机械保障见 [code-fix-lane](code-fix-lane.md)「收尾 salvage」）；子代理一律不验证、不提交。

## 溯源

- 2026-09-29 2026-09-29-add-codefix-batch-parallel（spec/archive/2026-09-29-add-codefix-batch-parallel） — 新建本页：批内并行处置协议（多组批派子代理、单组批退化串行）、orchestrator 单写者落盘、三级失败兜底、汇总后一次定向验证；并发上限后演进为框架按批组数分档注入（4/6/8），提交时序并入「先 commit 再验证」契约（逐组提交合法）。
- 2026-10-03 2026-10-03-add-codefix-commit-first-contract（spec/archive/2026-10-03-add-codefix-commit-first-contract） — 「汇总后一次验证一次提交」改写为「边修复边提交、收尾一次验证」：验证 MUST NOT 作为提交的前置条件（原「验证先行 + MUST NOT 多次提交」与先 commit 再验证契约互斥），逐组提交或收尾一次提交均合法，验证结果用于回归门前的自查补修、补修改动须再次 commit。
- 2026-10-04 2026-10-04-add-codefix-affinity-batching（spec/archive/2026-10-04-add-codefix-affinity-batching） — 派发节并发上限由模板固定常量改为框架按批内文件组数分档计算、经 `{wave_cap}` 占位符注入（分档 4/6/8，8 硬上限）；分档规则与缺省回退由 codefix-affinity-batching 页单源承载，本页只保留波次派发协议。
