# add-token-budget-escalation-tiers

## 背景与动机

dsh-plugins 的 add-session-advanced-search 全程累计消耗 input token 99,914,746（100M 预算的 99.9%，cost $98.51、38889s 墙钟、20 次 judge 实派），是同域后继优化轮 optimize-session-advanced-search（27.2M、2 次 judge、$23.72）的 3.67 倍（美元口径 4.15 倍，差额 $74.78）。期间预算治理的全部动作只有 warning 告警：80%/100% 两档均为警告级且代码明文「MUST NOT 修改 spec 状态（不自动冻结，design 决策有意为之）」（core/agent_runner/token_budget.py:296-302），95% 近满无任何档位；judge_rerun_cap（core/pm_engine/verification/judge_gate.py:46 _MAX_JUDGE_RERUNS=5）只封判定次数不封 token。唯一一次人工干预是 raise_budget 裁决把预算从 50M 翻倍到 100M（admin_alerts.json 告警 5f854ca87ce5，执行体 core/dashboard/data/admin_actions.py:2368）后续烧至 99.9M——止损通道事实上缺位。

结构性敞口已代码实锤：预算计数 per-spec（各条目 _tokens_in 独立累加）、阈值项目级全局配置、任何档位零自动动作；现存其他保护全部非 token 维度（max_turns 400 / impl_run_budget 4 / daily_run_limit 300 / run_timeout_seconds 9000 / infra_breaker）。下一个重型 spec（框架日常跑 web 真机验证的重型 spec）将结构性重演本例，即使击穿预算也只有再一条 warning。

## 目标

1. token 预算告警分级化：80% warning（现状保留）、95% major 进人工处置队列（admin_store.HUMAN_SEVERITIES 现成），recommended_action 列出收敛复验/冻结止损/raise_budget 三个处置选项；raise_budget 裁决执行时复位含新档在内的全部预算告警幂等标志。
2. judge 重跑上限与 token 余量联合判定：预算近满（ratio 达阈值）时把 spec 级剩余可重跑次数与轮内派发额度压缩，冻结/停派文案注明预算近满。
3. 预算近满自动切收敛复验模式：只复验「失败场景 ∪ depends_on 前置链（递归）∪ 下游场景」子集（复用 fastlane 子集计算基建），阈值独立配置且缺省关闭。

## 非目标

- 不改变 80%/100% 两档 warning 的既有发射行为（向后兼容）。
- 不引入 per-run 级 token 硬顶（run 级治理已有 max_turns/impl_run_budget/run_timeout_seconds，本 spec 只管 spec 级预算面）。
- 不做告警「自动冻结 spec」——沿用既有 design 决策（告警不改 spec 状态），制动经由 judge 既有硬闸的额度压缩与人工处置链实现。
- 不做 provider 拥塞治理与 API 停滞记账（独立问题域，另条目处理）。

## 交付物

core/agent_runner/token_budget.py（95% major 档 + severity 参数化发射 + 新幂等标志）、core/dashboard/data/admin_actions.py（raise_budget 幂等标志复位清单联动）、core/dashboard/data/config_admin.py（agents.token_conserve_ratio 受管键三面登记 + (0,1] 前置校验）、core/pm_engine/verification/judge_gate.py（token 余量联合判定）、core/pm_engine/verification/pipeline.py（预算触发源接入与通道优先级仲裁）、core/pm_engine/verification/fastlane.py（子集计算抽出复用入口）、tests/test_token_budget_escalation.py（单测）。

## 验收标准

- ratio>=0.95 触发 major 告警且幂等（同比例只发一次），进人工处置队列；ratio<0.95 不触发；80%/100% 旧行为不回归；「告警不自动冻结」语义保持。
- _exec_raise_budget 执行后全部预算告警幂等标志（含新增 95% 档）被复位，预算翻倍后 95% 档可再次正常触发。
- 预算近满时 judge spec 级剩余可重跑次数压缩为 1、轮内派发上限由 2 压缩为 1，文案注明预算近满；预算未近满时 judge 行为与现状完全一致。
- agents.token_conserve_ratio 配置生效时下一轮验证切收敛复验（子集=失败 ∪ 前置链 ∪ 下游），验证报告注明收敛模式与子集范围；缺省（未配置）行为与现状完全一致；与场景修订重验/排程重验的优先级仲裁落日志。