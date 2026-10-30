# 能力规格：stray-escalation-evidence-budget

## 需求

### R1 体积明细段预算

WHEN 构造 maintree_untracked_stray_escalated 升级信号的 evidence 时，系统 SHALL 对「条目体积(字节)」段套用与文件清单段同型的头部 N 项（N=50）截断，附「等 N 项」说明与体积合计聚合；全量体积 SHALL 引用注册表单源（sizes_bytes）而非内联进 evidence。

### R2 注入侧防御性体量上限

WHEN Administrator 提示词装配 signal evidence 时，系统 SHALL 施加防御性体量上限：超限时 fail-open 截断并附「已截断」注记，保证任意信号注入后的提示词长度有界。

### R3 处置失败限次重派

WHEN Administrator 处置 run 终态为 prompt_too_long（API 400）或 api_error 且 api_error_status=400 时，系统 SHALL 在孤儿处置恢复巡检内限次自动重派（复用既有 reschedule_max 上限）且重派 SHALL 携带瘦身 evidence。该终态落账为 final failed 处置组（result="failed"），重派实现 SHALL 覆盖该组的巡检路径（`_converge_final_orphan_group` 所在 final 组分支），MUST NOT 只改 interrupted 分支条件。重派/升级的关联信号判定 SHALL 对 daemon 级散件信号的 spec 记法失配形态（SIGNAL 记录 spec=None、处置组记录 spec=<项目名>）可达，MUST NOT 因 `unhandled_signal_for` 严格相等不命中而静默跳过。重派额度用尽时系统 SHALL 产生处置失败升级信号（落 ESCALATION 记录，severity=critical，不带 next_retry_at——不进入派发失败自动重试扫描），MUST NOT 让信号在无处置的情况下无限期挂「处置中」。

## 行为约束

- 升级触发阈值、归因探测语义、认领执行器行为均不变。
- 截断 MUST NOT 破坏 evidence 与 manifest 解析的写读成对性。
- 重派至多 reschedule_max 次，防止对同一坏信号形成重派风暴；限次用尽后的处置失败升级 MUST NOT 携带 next_retry_at 进入自动重试（派发失败重试扫描只消费带该字段的记录，其重试计数独立于 reschedule_count，纳入即突破重派总额）。
- 处置失败重派/升级对 daemon 级信号（SIGNAL spec=None、组记录 spec=<项目名>，既有 `_normalize_orphan_group_spec` 只归一 None↔"global"）MUST 关联可达；修复该记法口径时 MUST 维持在飞互斥、幂等与 unhandled_for 升级去重语义不变，且与既有孤儿收敛升级对同一信号不双升。
