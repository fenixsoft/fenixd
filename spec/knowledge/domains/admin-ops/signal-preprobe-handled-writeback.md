# 请求型信号前置探测闭环与处置回写

<!-- knowledge: capability=signal-preprobe-handled-writeback rev=1
     sources=spec/archive/2026-10-04-evo-signal-preprobe-handled-writeback -->

admin 信号摄取链路上的自动闭环层：诉求已被事实满足的请求型信号在唤起 Administrator 之前先行只读探测并闭环免唤起，处置 run 落终态时回写原信号 handled，使请求型信号的收尾不再只依赖人工通道（[alert-resolve](alert-resolve.md)）。

## 规则

- 前置探测发生在信号摄取循环内、mark_escalated 与唤起 Administrator 之前，仅对白名单 signal_type 生效。白名单收录三种产物存在性可判定类型：`verify_regression_missing`（项目 `.fenix/verify.yaml` 的 regression 段存在）、`verify_contract_missing`（验证契约文件/配置存在且可解析）、`build_artifact_paths_missing`（`worktree.build_artifact_paths` 非空，或 `has_build_artifacts=false`「确无产物」已裁决）。白名单外信号行为完全不变：照常冷却节流与唤起。
- 白名单收录门槛：新增类型必须同时给出只读探测谓词与「探测通过即无剩余动作」的语义等价论证方可入表；需语义判断的类型（manual-intervention、inconclusive_loop 等）永不收录。
- 探测只读：谓词仅检查目标产物/配置的存在性（读项目文件、读配置键），不写项目文件、不触发构建、不发起网络访问。
- 探测通过即闭环，三步同拍完成后跳过唤起：(1) 对信号调 mark_signal_handled 置 handled=true；(2) 同一记录同步 mark_escalated——摄取循环过滤只看 escalated，只写 handled 下一 tick 会被重捞、每周期重复探测并重复追加留痕；(3) 追加一条 `result=resolved` 的处置留痕（kind=disposition，action 注明「探测通过、诉求已满足、免唤起」，不带 admin_run_id——归并逻辑对无 admin_run_id 的记录跳过，不会伪造在飞 run）。
- 探测异常 fail-open：谓词抛错、存储不可读时按原有路径 mark_escalated 并照常唤起 Administrator，同时留「前置探测异常」警告日志可对账；探测器的自身缺陷不得吞掉信号。
- 处置终态回写：admin 处置 run 落最终 DISPOSITION 记录时，`result` 非 pending、`escalate` 为假且存在关联信号记录（signal_rec 非 None）时，对该信号回写 handled=true；回写失败仅记警告日志，不影响处置结果本身落盘。
- 回写两类豁免：`escalate=true`（升级人工，人工处置是唯一出路）不自动回写，由人工 alert-resolve 闭环；人工显式触发（signal_rec=None，处置无关联信号记录）跳过回写。
- 可对账：前置探测闭环与处置终态回写均落留痕（处置记录/框架日志），事后可查「为何未唤起」「何时回写」。

## 溯源

- 2026-10-04 evo-signal-preprobe-handled-writeback（spec/archive/2026-10-04-evo-signal-preprobe-handled-writeback） — 新增请求型信号摄取前置探测白名单闭环（探测通过免唤起、同步 escalated 防重捞、异常 fail-open）与处置终态 handled 回写（escalate/无关联记录豁免、失败降级警告）
