# ADR-347：裁决选项风险档位收敛静态注册表单源、缺档 terminal 保守兜底

date: 2026-11-11
status: accepted

## Context

裁决自动执行需要按动作不可逆性分级（白名单内外一刀切不再适用于分级自动化）。档位判定必须防漂移：若在告警发射时逐条拷贝档位，违反「三处同源禁复制」既有纪律，注册表与存量告警数据漂移风险高；历史或新增条目漏声明档位时若放行自动执行则方向危险。

## Decision

- risk_tier 作为 choice 条目字段收敛在静态注册表单点（core/dashboard/data/adjudication_choices.py），与 signal_type→choices 映射同源；档位读取单点 choice_risk_tier。
- 缺档或枚举外脏值一律按 terminal（最保守）兜底——永不因漏档误自动执行；import 期一致性自检扩为五元组（action/scoped/destructive/requires_payload/tier），跨桶共享 id 档位漂移即拒绝启动。
- 档位声明不改变既有 choice 解析、payload 校验与执行行为；发射点零拷贝，策略引擎与未来消费方一律读时从注册表解析。

## Consequences

- 新增选项必须声明档位，漏声明是安全方向（不自动执行）而非危险方向。
- 档位语义演进只改注册表一处，存量告警记录无需迁移（choices 快照不含档位）。
- 自动执行面被结构性限定在 reversible-experiment 档；放宽到其他档位须显式 supersede。
