# 能力规格：stray-escalation-evidence-budget

## 需求

### R1 体积明细段预算

WHEN 构造 maintree_untracked_stray_escalated 升级信号的 evidence 时，系统 SHALL 对「条目体积(字节)」段套用与文件清单段同型的头部 N 项（N=50）截断，附「等 N 项」说明与体积合计聚合；全量体积 SHALL 引用注册表单源（sizes_bytes）而非内联进 evidence。

### R2 注入侧防御性体量上限

WHEN Administrator 提示词装配 signal evidence 时，系统 SHALL 施加防御性体量上限：超限时 fail-open 截断并附「已截断」注记，保证任意信号注入后的提示词长度有界。

### R3 处置失败限次重派

WHEN Administrator 处置 run 终态为 prompt_too_long 或 api_error（API 400 类错误）时，系统 SHALL 限次自动重派（复用既有 reschedule_max 上限）且重派 SHALL 携带瘦身 evidence；重派额度用尽时系统 SHALL 产生处置失败升级信号（落 ESCALATION 记录），MUST NOT 让信号在无处置的情况下无限期挂「处置中」。

## 行为约束

- 升级触发阈值、归因探测语义、认领执行器行为均不变。
- 截断 MUST NOT 破坏 evidence 与 manifest 解析的写读成对性。
- 重派至多 reschedule_max 次，防止对同一坏信号形成重派风暴。
