# codefix-dispatch-cooldown

## Requirements

### R1 连接类失败识别

- 车道失败分类 MUST 以组合条件判定「连接类 api_error」：terminal_reason == "api_error" 且 exit_code != 0 且 result_text 命中连接类签名词表。
- 连接类签名词表 MUST 覆盖实测死因形态：「Can't reach the API server」「ENOTFOUND」（MUST 以 code-fix 车道本地词表常量实现，MUST NOT 扩充共享 SWITCH_ERROR_CONN_PATTERNS——该词表被 classify_switch_error 消费、扩充将改变 spec/impl 车道既有切换行为，见 design D1）。
- MUST NOT 以 stderr 是否含 unrecognized_model 作为判据（该行是 glm/deepseek 链每 run 必有的定噪，provider_circuit.py CLI_STDERR_NOISE_TEXT_PATTERNS 自证）。
- MUST NOT 走 record_unrecognized_model/链条目摘除语义（该语义是「确定性拒模型」，对连接故障会产出错误运维建议）。
- 单轮 API 超时（result 含 "Request timed out" 且非连接类）MUST 保持既有 api_timeout/salvage 语义不变。

### R2 车道级推迟重派（冷却）

- code-fix 车道批次失败收尾命中 R1 时，MUST 置同链冷却态：下一批派发时刻不得早于「失败时刻 + 冷却时长」。
- 冷却时长缺省复用 PROVIDER_SWITCH_COOLDOWN_SECONDS（300s > 实测约 101 秒窗口），MUST 支持配置键 admin.code_review_fix.switch_cooldown_seconds 覆盖，非法值（负数/NaN/inf）回退缺省、0 表示关闭。
- 冷却态 MUST 持久化（fix-progress.json 新增 switch_cooldown_until epoch 字段，合并写），进程重启后仍生效。
- 冷却守卫 MUST 挂在 checkpoint 投递入口（全部激活路径的唯一共用入口：full scan 末尾兜底/新条目激活/自驱动 _resubmit/事件驱动重试均汇入 checkpoint），MUST NOT 只拦自驱动一路。
- 冷却期 MUST NOT 改变失败批条目记账语义：consumed/chain_skipped 保持现状，仅推迟下一批投递。

### R3 告警与跨日指纹升级

- 冷却触发与解除 MUST 经 AdminStore 写 kind=SIGNAL 告警（signal_type=code_fix_switch_window_deferred，source=code-fix-lane，evidence 携带 run_id/死因文本/到期时刻），拒写走既有留痕路径。
- admin_monitor daemon_errors 指纹记账 MUST 增加「跨日同刻复发」维度：同签名失败终态时刻跨日差 ≈24h（容差 ±5 分钟）即升级 escalation，MUST NOT 被已知指纹 30 分钟冷却压制。

### R4 验收

- 注入连接类失败后，[T, T+冷却时长] 窗口内 MUST 无新批 worktree 创建与 run 派发；冷却到期后首批正常投递。
- 观测面：失败终态日志行 + 新批启动三件套（worktree 创建/agent_env 注入/run 启动）+ 相邻 run epoch 差 ≥ 冷却值（run id 即派发 epoch）。

## Scenarios

1. **连接窗口内失败 → 推迟重派**：批次 A 于 T 时刻死于 ENOTFOUND（exit 1、api_error）→ 冷却态落地 → 3 秒后的自驱动重派请求被 checkpoint 拦下 → T+300s 后批次 B 正常投递并成功；窗口内新建树/派发日志为 0。
2. **单轮超时不误伤**：批次死于 result 含 "Request timed out" 且 result_text 无连接类签名 → 不置冷却，行为与现状一致（salvage 判定 + consumed 重派）。
3. **成功 run 零影响**：正常完成批次无冷却态、无告警；glm 链成功 run 的 stderr unrecognized_model 定噪行不触发任何分类。
4. **跨日复发升级**：同指纹失败今日 20:31 与昨日 20:31 各一次 → daemon_errors 记账判跨日同刻复发 → 出 escalation 告警（30 分钟已知指纹冷却不吞）。
5. **重启后冷却仍有效**：冷却态落地后进程重启 → checkpoint 在冷却期内仍拒绝投递。