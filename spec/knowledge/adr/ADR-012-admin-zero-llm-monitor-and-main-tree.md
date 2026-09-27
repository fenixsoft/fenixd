# ADR-012：自愈监视零 LLM 成本，Administrator 直接操作主树

date: 2026-09-02
status: accepted

## Context

无人值守自愈需要「周期性健康监视 + 困境处置 + 人工兜底」三层。若监视本身依赖 LLM，则高频轮询的成本不可接受（每数分钟一次完整 agent 判定日均数百美元，且多数结论是「一切正常」）。同时 Administrator 作为框架自愈角色，其工作层级与开发角色不同，须显式裁定。

## Decision

- 监视器是 daemon 内的轻量线程：按固定间隔读取本地数据（STATE.md、run 转录、日志）做规则检测（重复失败、状态抖动、卡死、熔断滞留、连续 ERROR 等可配阈值信号），全程零 LLM 调用。
- 仅当检测到困境信号且通过节流（同 spec 同类信号冷却窗口内只唤起一次）时，才以 `claude -p` 子进程唤起 Administrator agent；Administrator 只做困境处置，不参与日常开发。
- Administrator 是运维角色：其处置（含修改框架自身代码）直接在 main 树进行并 commit，不走 implementer 的 worktree 隔离——框架自愈代码本就属于主树。
- Administrator 受「仅处置不开发」约束，处置前先只读诊断，动作全部留痕（告警/处置记录 append-only 落盘）；无法处置的事件结构化升级为人工告警。
- 整体能力有配置开关，默认可一键停用。

## Consequences

- 自愈的常态成本趋近于零，LLM 花费只发生在真实困境上；人类告警面收敛到「真正需要人类」的事件。
- 主树直写意味着 Administrator 处置与用户未提交工作共享同一工作区，须以留痕与先诊断后动作的纪律约束误操作风险；框架代码被处置修改后须重启 daemon 才生效。
