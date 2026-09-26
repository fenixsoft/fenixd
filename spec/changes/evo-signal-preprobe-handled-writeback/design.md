## 落点

- 前置探测：core/admin_monitor.py 信号摄取循环 _detect_family_explosion（run_once :930 调用）内、mark_escalated / _invoke_administrator 之前插入探测守卫；信号类型收录表在 :437 附近，白名单常量置于同文件收录表旁。
- 终态回写：core/agent_runner/maintenance_runs.py 处置结果写入处（run 启动写 pending :234 附近、终态写 result=resolved/failed :316 附近），终态分支调用 AdminStore.mark_signal_handled（core/admin_store.py:365）。

## 探测谓词

按 signal_type 分派，全部只读：

- verify_regression_missing：读项目 .fenix/verify.yaml，regression 段存在即通过（可复用 core/verify_contract.py 的契约装载做存在性判断，不落盘、不执行脚本）。
- verify_contract_missing：项目验证契约文件/配置存在即通过。
- build_artifact_paths_missing：项目 config 的 worktree.build_artifact_paths（或 has_build_artifacts 裁决）非空即通过。

## 数据流与留痕

- 探测通过：AdminStore.mark_signal_handled(信号 id) + 追加 kind=disposition、result=resolved 记录（字段与 maintenance_runs 写入的处置记录同构，action 注明 pre-probe auto-resolve：探测通过、诉求已满足、免唤起），随后 continue 跳过唤起。
- 终态回写：处置 result 非 pending 时对处置对象引用的信号 id 调 mark_signal_handled；异常捕获降级为 logger.warning，不阻塞处置结果落盘（对齐 R5）。

## 风险与防误杀

- 误闭环真实诉求：白名单只收「产物存在性」可判定类型，探测谓词与诉求满足是同一事实（段/文件/配置已存在），语义等价。
- 探测器自身缺陷吞信号：R4 fail-open + R6 留痕双保险；探测异常路径与现有唤起路径完全一致，回归面为零。
- 白名单膨胀：新增类型必须同时给出只读谓词与「满足即无剩余动作」论证方可入表；需语义判断的类型（manual-intervention、inconclusive_loop 等）永不收录。

## 测试策略

tests/test_signal_preprobe_handled_writeback.py：进程内装配 AdminStore + 监视器最小夹具，覆盖探测通过免唤起、探测不通过照常唤起、探测异常 fail-open、处置终态回写 handled=true 四例，外加白名单外行为不变一例。