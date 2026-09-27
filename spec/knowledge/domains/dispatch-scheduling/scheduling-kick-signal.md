<!-- knowledge: capability=scheduling-kick-signal rev=1 sources=spec/archive/2026-09-25-fix-scheduling-kick-single-slot -->

# 调度踢一脚（kick）信号

「清空定时拾取 / 激活 SPEC」触发的即时唤醒文件信号：每 SPEC 一文件的载体、如实回报、逐条消费与陈旧回收。

## 现行规则

- 信号载体为每 SPEC 一个文件，落盘于 `.fenix/scheduling_kick/`，文件名 `<spec>.json`；内容为 JSON 对象：`spec`（SPEC 名）、`action`（`"clear-start-after"`）、`created`（写入时刻 UTC ISO8601）。
- 写入为原子操作（临时文件 + `os.replace`）：临时文件不以 `.json` 结尾且与目标文件同目录；消费侧只识别 `.json` 后缀，不把写入中的临时文件当信号消费或删除。消费侧可见的要么是完整合法 JSON、要么是该 SPEC 无文件。
- 写入侧校验 SPEC 名合法性：为空、含路径分隔符（`/`、`\`）、含 `..` 或与文件名规则不符者拒绝写入并返回明确错误，不拼接逃逸目录的路径；判据复用既有 kebab-case 权威校验，不采用仅覆盖少数危险字符的黑名单。
- 不同 SPEC 的信号互不干扰：任一 SPEC 的写入不因其它 SPEC 已有未消费信号而失败或被丢弃；同一 SPEC 重复写入幂等（覆盖自身文件）。
- 写入结果如实回报、不静默吞掉：写入助手返回 `{"ok": bool, "file": str|null, "error": str|null}`；触发写入的动作函数（`set_spec_start_after` 清空分支、`activate_spec`）在返回值中携带 `scheduling_kick` 键；Dashboard API（`POST /api/spec-start-after`、`POST /api/spec-activate`）把结果透出到响应体——信号写入失败时响应携带非空 `warning`（「即时唤醒未生效、将由后续扫描派发」）且 `ok` 仍为 true；API 不得在信号写入失败时宣称「立即恢复调度」。
- 前端依据响应 `warning` 字段选择文案：无该字段提示「立即恢复调度」；有该字段提示「已清除定时，但即时唤醒信号写入失败，将由下次扫描（缺省 ≤30 分钟，即 `schedule.poll_interval_minutes`）派发」。
- 消费侧逐条消费：daemon 每次主循环轮询扫描目录 `.json` 条目，对每个信号执行「读取 → 按 SPEC 当前状态唤起派发 → 唤起成功后删除」——`drafted` 走晋升链，其余状态走 `_on_spec_ready`；唤起后立即处理派发队列。逐条消费相互隔离：单条信号处理异常不阻止同轮其余信号消费，异常者的信号文件保留至下一轮重试。
- 兼容存量单文件路径 `.fenix/scheduling_kick_request.json`：存在时按既有语义消费并删除，与目录条目同受陈旧回收阈值约束；新写入不再产生该单文件路径。
- 损坏 / 非法 JSON / 缺少 `spec` 字段的信号文件被删除（防每轮报错卡死），删除失败时下轮重试；SPEC 已不在 STATE.md 时删除信号并记日志。
- 陈旧唤醒信号自动回收：daemon 启动清扫与周期计时段（600 秒节拍，与既有孤儿清扫同时点）对目录执行对账回收——`created` 距当前时刻在回收阈值内的条目先行消费（唤醒幂等，重复唤醒被下游既有谓词吸收）再删除；早于阈值的判陈旧，仅删除、不唤起（防 daemon 长期停机后的病态集中派发），该判据同样适用旧单文件路径。回收阈值为代码常量（1 小时），不进项目配置。

## 溯源

- 2026-09-25 2026-09-25-fix-scheduling-kick-single-slot — 唤醒信号载体由单文件单槽位改为每 SPEC 一文件，消除跨 SPEC 槽位冲突的静默丢弃与未消费单文件的永久占槽（实证清空定时后空等 22.5 分钟而接口返回假成功）；同时落地写侧如实回报、消费侧逐条隔离与陈旧信号自动回收。
