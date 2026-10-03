## 落点

- 前置探测：core/admin_monitor.py 信号摄取循环 _detect_family_explosion（run_once :930 调用）内、mark_escalated / _invoke_administrator 之前插入探测守卫；信号类型收录表在 :437 附近，白名单常量置于同文件收录表旁。
- 终态回写：core/admin_monitor.py _invoke_administrator 内最终 DISPOSITION 落盘处（store.append 写 kind=DISPOSITION 终态记录，:3440-3474 附近）——注意非 maintenance_runs.py：该文件只写 run 启动的 pending 记录（:220-237）与构造 AdminDisposition 返回对象（:310-328，不落盘），终态 DISPOSITION 记录由 _invoke_administrator 在 run_administrator 返回后落盘（:3323 注释即此约定）。回写用参数 signal_rec.get("id")（原始 SIGNAL 记录 id 仅在该作用域可得）；人工显式触发路径 signal_rec=None（:3330）无关联记录，跳过回写。

## 探测谓词

按 signal_type 分派，全部只读：

- verify_regression_missing：读项目 .fenix/verify.yaml，regression 段存在即通过（可复用 core/verify_contract.py 的契约装载做存在性判断，不落盘、不执行脚本）。
- verify_contract_missing：项目验证契约文件/配置存在即通过。
- build_artifact_paths_missing：项目 config 的 worktree.build_artifact_paths（或 has_build_artifacts 裁决）非空即通过。

## 数据流与留痕

- 探测通过：AdminStore.mark_signal_handled(信号 id) **并同步 mark_escalated(同一 id)**（摄取过滤只看 escalated，_detect_family_explosion 循环 :1781——只写 handled 下一 tick 会被重捞、每周期重复探测并重复追加留痕；与既有终态守卫/前提复核守卫 mark_escalated+continue 同范式）+ 追加 kind=disposition、result=resolved 记录（字段与 maintenance_runs 写入的处置记录同构，action 注明 pre-probe auto-resolve：探测通过、诉求已满足、免唤起；不带 admin_run_id——_merge_admin_runs 对无 admin_run_id 的记录跳过归并（:608-610），不会伪造「在飞 run」，先例同冷却跳过留痕 :3395-3408），随后 continue 跳过唤起。
- 终态回写：_invoke_administrator 落最终 DISPOSITION 后，disp.result 非 pending 且 disp.escalate 为假且 signal_rec 非 None 时，对 signal_rec.get("id") 调 mark_signal_handled（escalate=true = 升级人工，人工处置是唯一出路——对齐 :3504 既有范式，由人工 alert-resolve 闭环；人工显式触发路径 signal_rec=None 无对象，跳过）；异常捕获降级为 logger.warning，不阻塞处置结果落盘（对齐 R5）。

## 风险与防误杀

- 误闭环真实诉求：白名单只收「产物存在性」可判定类型，探测谓词与诉求满足是同一事实（段/文件/配置已存在），语义等价。
- 探测器自身缺陷吞信号：R4 fail-open + R6 留痕双保险；探测异常路径与现有唤起路径完全一致，回归面为零。
- 白名单膨胀：新增类型必须同时给出只读谓词与「满足即无剩余动作」论证方可入表；需语义判断的类型（manual-intervention、inconclusive_loop 等）永不收录。

## 测试策略

tests/test_signal_preprobe_handled_writeback.py：进程内装配 AdminStore + 监视器最小夹具，覆盖探测通过免唤起、探测不通过照常唤起、探测异常 fail-open、处置终态回写 handled=true 四例，外加白名单外行为不变一例。