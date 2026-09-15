# stuck-signal-hygiene — stuck 信号活跃度预检与处置后静默

> 首版因方案漏洞被评审否决（reject）：D1 依赖不存在的 pid 数据源、D2 与既有 `merge_signal` 语义重叠、D3 定义不明。修订后 D1 复用既有 `AgentRunner.running_run_ids()` 公开 API，D2 改为不新增代码仅补回归测试，D3 明确锚点与查询。

## 场景：run 文件陈旧但 agent 子进程存活

- 前置：spec 处于 `implementing`，`updated` 超 stuck 阈值；该 spec 有登记在跑的存活 run（`AgentRunner.running_run_ids()` 命中），但转录文件停止增长（mtime 超出宽限）。
- 行为：`_detect_stuck` 判定进程存活 → **非 stuck**，不产生信号（D1）。

## 场景：进程存活但无输出的 hang

- 前置：run 进程存活但长时间无 token 产出。
- 行为：不判 stuck（D1 接受该代价）；由 `agents.run_timeout_seconds` 超时终止兜底，超时后进程退出 → 下一轮巡检按「无存活进程」正常判 stuck。

## 场景：同 (spec, signal_type) 状态未变重复触发

- 前置：冷却窗口内同 `(spec, signal_type, status_hash)` 重复触发（如 09-14 连发场景）。
- 行为：**既有 `merge_signal` 状态沉淀**——不新增 signal 记录，只刷 `last_seen`（每轮巡检只保留首条）。本 SPEC 仅以回归测试锁定该行为，不新增去重代码（D2）。

## 场景：处置 resolved 后复发

- 前置：`(spec, signal_type)` 最近一条 `kind=disposition` 且 `result∈{resolved, partially-resolved}`，不久后同信号再次满足触发条件。
- 行为：距处置时刻 `admin.stuck_silence_minutes`（默认 120）内不产生信号；静默期后状态仍异常时允许新信号（D3）。

## 场景：admin 升级人工后

- 前置：最近处置 `result=escalated`（admin 判定无法自主处置、升级人工）。
- 行为：**不触发静默**——人工处置是唯一出路，同信号继续正常产生（D3 边界）。

## 场景：真实 stuck

- 前置：无存活 run + 无文件活跃 + 无近期 resolved 处置。
- 行为：正常产生 stuck 信号，不静默（D5 兼容）。

## 非目标

- 不改 stuck 主判据（`updated` 超阈值）本身。
- 不改 baseline reset（extension）机制。
- 不处理「进程存活但 hang」场景（交由 `run_timeout_seconds` 超时兜底）。
- 不新增 signal 记录层去重代码（由既有 `merge_signal` 承担）。
