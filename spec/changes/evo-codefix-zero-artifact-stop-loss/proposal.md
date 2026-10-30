# 提案：codefix-zero-artifact-stop-loss

## 问题

10-26 凌晨 code-fix 台账修复链在 dsh 车道连续 3 个编排 run 空转失败（code-fix-1792952924/1792953101/1792953322，fenixd.log:1177/1192/1210）：主代理后台派发 8 组子代理后以「结束回合等完成通知」收尾（claude 车道语义），dsh 会话随主回合终止，修复产物 out 文件从未写出，产物硬门 _check_code_fix_artifact（core/agent_runner/maintenance_runs.py run_code_fix 收尾「产物硬门」块；行号随主干并发演进漂移，实现以符号定位）连拦 3 次；第四个 run code-fix-1792953479 同型收尾仅 1 组落盘却过硬门。四 run 合计 36 次子代理派发约 35 组作废，链首 fully-productive 收尾推迟 43 分钟。

当晚 Administrator 已用 commit 9ccf90158/4c2fc3a9d 将 agents/code-fix.md:45-56 改为同步并发派发契约（「回合结束 = run 终止」「MUST 用 run_in_background: false」）止血，后续 code-fix-1792954299/1792955804 两个 dsh run 全量成功。但残留两个系统性缺口：

1. 该契约是纯模板文本，无任何测试锚定——模板漂移即静默复发（同类先例 tests/test_prompt_lane_efficiency_sections.py:73-81 锚定 implementer/fast-track 后台等待段，code-fix 无对应物）。
2. 重试环路对「会话正常结束但产物缺失」形态无同指纹止损：硬门失败信封 conn_error 恒 False（CodeFixResult 信封 conn_error 缺省 False、仅 api_error 异常路径置真——类定义 core/agent_runner/result_gate.py、maintenance_runs 失败收尾初始化），首轮失败一律按 chain_skipped 瞬态继续推进（core/code_fix.py CodeFixChain._run_batch_inner 首轮 run 失败收尾块），同配置连派 3 次全靠随机性过关；唯一的连败熔断是回归 parse-error 域（core/code_fix.py 回归异常熔断 anomaly_streak，位于回归失败后的定向重试循环内），不覆盖 run 级零产物。

## 目标

1. 产物硬门零产物失败透出结构化失败类别，code-fix 链对同指纹 artifact_missing 连败 ≥2 次即止损（停止该指纹重派＋留痕告警），不再依赖随机性过关。
2. 契约测试钉住 agents/code-fix.md 的同步派发/等待契约（含已热修条款防回归）。

## 非目标

- 不重写 agents/code-fix.md 派发契约（9ccf90158/4c2fc3a9d 已落地并经两个成功 run 后验，作为现状基线只锚定不改动）。
- 不触碰 evo-add-instant-fail-cooldown-full-lane-gate 的进程秒死冷却（其管启动存活 <60s，本 SPEC 管「正常退出但产物缺失」）。
- 不新增 admin 告警通道，止损留痕复用既有告警/日志路径。
- 不改 admin_monitor 同指纹告警升级语义（≥2 次/≤5 分钟），那是告警召唤不是派发止损。
