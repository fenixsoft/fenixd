# impl 环境阻塞止损与任务停滞预警
<!-- knowledge: capability=impl-env-blocker-stop-loss rev=1
     sources=spec/archive/2026-10-14-evo-add-impl-env-blocker-stop-loss -->

impl run 对环境阻塞任务的止损纪律与「自最近任务完成起 N 轮」停滞预警观测面：环境缺口不在 run 内无限深挖，长期零任务完成在轮数上限击杀之前就有在途信号。run 级判停类止损（取消旗标/重试让位/延迟停滞预算）见 [run 级止损](run-stop-loss.md)。

## 规则

- **环境阻塞止损（提示词硬规则）**：任一环境依赖在同一 run 内连续 ≥3 次失败尝试（按尝试次数计，不按错误签名——错误码漂移不代表是不同问题）即冻结该任务：design 有 fallback 条款先走 fallback；否则登记为 unfinished 并以 partial 收工、继续其余任务。implementer MUST NOT 在 run 内为救单个验证场景对宿主做内核级/镜像级不可逆改造（内核模块替换、系统镜像降级等），环境缺口走 env 升级或环境供给层；verify.yaml prepare 层的幂等宿主环境预置不在禁令之列。
- **任务书环境依赖标注**：环境依赖类任务在任务书中标注「环境依赖、有/无 fallback」类别，供止损规则联动——无 fallback 的环境阻塞任务触发止损时直接登记 unfinished，不被迫临场发明回退路径。
- **任务进度停滞观测**：框架对 impl run 维护「自最近一次 run 内任务完成起的轮数」计数，数据源为 run 流内 TaskUpdate completed 观测（run_task_track 单点解析），MUST NOT 使用主树 tasks.md 口径（worktree run 期间它恒静态）。超过阈值即打一条 WARNING（event=task_stall_warn，含停滞轮数/阈值/已完成任务数）并在 run_metrics 附停滞注记，run 继续正常执行。
- **观测面配置**：`agents.task_stall_warn_enabled`（缺省开启，纯观测无副作用故无需灰度）与 `agents.task_stall_warn_turns`（阈值，缺省 200 轮，按观测调参），经 `ConfigLoader.get_task_stall_warn_config` 单点归一化，runner 消费与设置展示同源，非法值回退缺省。
- **观测不判定**：停滞观测只注记不判定，不参与续期/击杀判定，不与 kill_early、延迟停滞预算（`agents.run_stall_budget_*`）互相触发；既有预算 sizing 与判停语义不变。
- **预警一次性与锚点重置**：同一段停滞期只报一次 WARNING；观测到新任务完成即重置锚点轮数并复位已报标记、重新起算。
- **观测面开销边界**：轮询路径的流内计数沿增量位点缓存，仅在流文件变化时重扫；MUST NOT 每轮全量重扫 run 流（600 轮 run 上是 O(N²) IO）——观测面自身不得成为轮询开销放大器。

## 溯源

- 2026-10-14 evo-add-impl-env-blocker-stop-loss（spec/archive/2026-10-14-evo-add-impl-env-blocker-stop-loss） — 新增本页：implementer 提示词环境阻塞止损硬规则（连续 3 次失败按尝试计数冻结、禁宿主级不可逆改造）、planner 任务书环境依赖标注联动、`agents.task_stall_warn_*` 停滞预警观测面（缺省开启、只注记不判定）
