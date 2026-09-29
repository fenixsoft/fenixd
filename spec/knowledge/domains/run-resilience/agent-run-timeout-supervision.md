<!-- knowledge: capability=agent-run-timeout-supervision rev=2 sources=spec/archive/2026-09-02-improve-run-lifecycle-governance,spec/archive/2026-09-19-fix-run-hang-amplification -->

# Agent run 超时监督（活性评估与续期）

agent run 到达墙钟时限后的活性评估、续期与确定性停滞判定：既防长跑 run 无限占用预算，也防仍在推进的 run 被到点硬杀。

## 现行规则

- agent run（implementer/tester 等）到达 `agents.run_timeout_seconds`（缺省 3600 秒，Dashboard 配置页可调）时，系统先进入活性评估流程；仅当评估结论为「停滞」（含可观测零产出的确定性短路判定）或受限条件触发时才终止进程。`agents.timeout_supervision.enabled=false` 时回归纯墙钟行为（到点硬杀，按 interrupted 语义落终态）；相关配置键缺失时使用文档化默认值，不影响主流程。
- 活性评估以 run 流的可量化证据为输入：窗口内实质事件的时间戳间隔与数量、工具完成数、心跳数、是否重复相似操作、窗口内被等待的后台调用及其输出文件增长情况；由独立于被判定 run 的 LLM 给出 advancing / stagnant 结论。判定口径的硬约束：心跳事件不计入进度证据；窗口内无实质事件时直接判停滞、不经 LLM；持续产出心跳事件或 I/O 增长不单独构成 advancing 的充分依据。
- 可观测零产出确定性短路：仅当「run 阻塞等待某后台调用不短于固化阈值」「该后台调用关联输出文件可观测且窗口内零增长」「窗口内工具完成数低于固化阈值」三条件同时成立时，方可不经判定 LLM 直接判停滞进入终止路径；短路判定在 run jsonl 与 daemon 日志中标注为启发式「零产出」判定，并记录后台调用标识、输出文件路径与观测到的零增长区间。任一条件不成立（尤其输出文件不可观测）时必须走 LLM 判定路径。重复相同工具调用占比与工具结果文本重复度不得作为停滞判据。
- 判定 LLM 调用失败（网络异常、网关拒绝）且未触发确定性短路时，本次按停滞处理终止进程，日志与 run 文件记录「liveness judge unavailable」。
- 判定 advancing：将该 run 时限延长 `agents.timeout_supervision.extension_seconds`，并向调度器广播续期事件使 stuck 检测起始时间随之顺延。判定 stagnant：立即终止并按既有失败路径处理，run 文件包含证据摘要（实质事件数、工具完成数、心跳数，零产出判定时另含输出文件与零增长区间）。
- 续期双重封顶：`agents.timeout_supervision.max_extensions` 次数上限与 `agents.timeout_supervision.absolute_max_seconds` 总时长上限；任一封顶命中即不再评估、直接终止并记录「extension budget exhausted」。
- 每次评估与续期决策写入 run 文件与 daemon 日志供审计。

## 溯源

- 史前复原 — 迁移期基线：agent 运行超时缺省 1 小时，Dashboard 配置页可调；超时由监督线程强杀并记 interrupted 语义
- [2026-09-02 improve-run-lifecycle-governance](spec/archive/2026-09-02-improve-run-lifecycle-governance/) — 确立到限先活性评估再终止的流程：证据驱动 LLM 判定、advancing 续期与续期双重封顶、enabled 开关与失败安全回退
- [2026-09-19 fix-run-hang-amplification](spec/archive/2026-09-19-fix-run-hang-amplification/) — 判定口径改为实质事件/心跳分离，心跳不构成推进证据；新增可观测零产出确定性短路；排除重复调用形态判据
