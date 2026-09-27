# design: add-codefix-digest-cost-metrics

## D1 工具构成统计挂点：runner context metrics

core/agent_runner/runner.py 的 context metrics 汇总处（:4936 日志行所在函数；「落盘失败不阻断终态」的既有语义 :4971 保留）：转录解析处逐事件流过 assistant 事件，累计 tool_use 按名计数（Read/Edit/Bash/Grep/Agent 等）与无 tool_use 的 assistant 文本行数，与 turns 并列打进 context metrics 日志与落盘。统计口径先例见 core/agent_runner/latency.py:150-193（rounds/stall 按转录事件累计）。

## D2 链级 rollup 挂点：code-fix 链末批判定处

core/code_fix.py 已有链末批判定 is_chain_last_batch（:1109，add-code-fix-batch-failure-selfheal 交付）：末批合回处汇总本链各 run 的轮数/tool_use（读 run 归档计数）与台账核销计数（resolved/ignored，按 review 维度台账为准），打一行结构化 rollup 日志并随链状态落盘；链中途终局（失败/跳批）同样输出累计值。选批与装箱（select_batch :1061、_pack_first_batch :1002）不动。

## D3 非目标：severity 预聚类不立项

归因抽样显示：文件亲和已交付「同文件多条同批」（_group_open_items_by_file :988 / _pack_first_batch :1002），轮数大头是难条目固有取证成本（grep/Read/sed 约占 tool_use 一半）与批固定开销摊薄（每批约 270 轮、每条边际约 4 轮）；severity 预聚类只把易条目分进便宜批、不动难条目取证成本，且批变小本身恶化固定开销摊薄。先落度量，待链级 rollup 数据积累后再评估批结构参数（batch_size/target）。

## 风险

- tool_use 计数与 turns 并存可能被误读：日志字段名显式（tool_uses/text_turns），rollup 里两者都给。
- 链跨 daemon 重启：rollup 以台账核销与 run 归档计数为准，不依赖内存态。