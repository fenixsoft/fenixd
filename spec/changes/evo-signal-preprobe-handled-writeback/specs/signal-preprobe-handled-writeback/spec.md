## 能力：admin 请求型信号摄取前置探测与处置闭环回写

### R1 前置探测白名单

信号摄取循环在 mark_escalated 与唤起 Administrator 之前，仅对白名单 signal_type 执行前置探测。初始白名单：verify_regression_missing、verify_contract_missing、build_artifact_paths_missing。白名单外信号行为完全不变。

### R2 探测只读

探测谓词必须只读：仅检查目标产物/配置的存在性（如项目 .fenix/verify.yaml 的 regression 段、验证契约文件、worktree.build_artifact_paths 配置键），不得写项目文件、不得触发构建或网络访问。

### R3 探测通过即闭环

探测通过时：调用 AdminStore.mark_signal_handled 将信号置 handled=true，并追加一条 result=resolved 的处置留痕（注明「探测通过、诉求已满足、免唤起」），随后跳过 Administrator 唤起。

### R4 fail-open

探测执行异常（谓词抛错、存储不可读）时按原有路径继续 mark_escalated 与唤起，不得因探测失败静默吞掉信号。

### R5 处置终态回写

admin 处置 run 写入非 pending 的最终处置结果时，必须回写对应信号的 handled=true（复用 AdminStore.mark_signal_handled），使原信号不再永挂未处理；回写失败仅记警告日志，不影响处置结果本身落盘。

### R6 可对账

前置探测闭环与终态回写均须落留痕（处置记录/框架日志），事后可对账「为何未唤起」「何时回写」。