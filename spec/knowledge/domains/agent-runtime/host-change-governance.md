<!-- knowledge: capability=host-change-governance rev=1 sources=spec/archive/2026-10-13-evo-add-host-change-governance -->

# 宿主系统级变更治理

agent 对宿主系统级资源（内核模块、dkms、系统包、设备节点）做变更时的备份与登记契约，以及 run 失败终态下回滚义务的自动告警闭环：义务在变更发生时即时落盘，不随 run 被击杀或 worktree 清理丢失；框架只派发告警，回滚执行永远由人工裁决。

## 规则

- 适用对象：implementer 与 administrator agent 对宿主系统级资源的替换、修改与覆盖动作。能用户态解决的 MUST NOT 动系统级。
- 先备份：变更前 MUST 备份原版本，备份内容含文件路径、版本与加载参数。
- 即时登记：变更发生时 MUST 即时写入 worktree 根 `host_changes.json` 登记文件（与 `.fenix-run-result.json` 同级、增量追加），元素含变更对象路径、版本、备份位置与回滚指引。登记文件是回滚义务的唯一权威载体；run 结果中的 `host_changes` 汇总只是收尾冗余，result-bearing run 两处内容 MUST 一致——击杀类终止无 run-result、拷回也不发生，义务只靠登记文件存活。
- 回滚指引：收工时变更仍在位的，登记 MUST 附可执行回滚指引。
- 失败终态派发：run 终态为失败（error/killed，含超时、轮次上限、判停等无 run-result 的击杀类终止）且登记非空时，框架在 runner 终态记录点（先于 worktree 清理）读取登记文件，自动向 admin 告警通道派发「回滚义务」告警；派发后 worktree 整目录删除，告警仍存活。
- 告警形态与去重：kind=escalation、severity=major、signal_type=`host_change_rollback_obligation`，内容含变更清单与回滚指引；去重键=spec+变更对象路径，在途同键重复派发不落新条，mark_handled 闭环后才落新条；跨 spec 同对象路径照常各自落地不串扰。
- 人工裁决：告警只增不执行，框架不自动执行 rmmod/depmod/modprobe/包还原等任何宿主还原动作，回滚执行由维护者/admin 人工裁决。
- 成功终态：登记在场时仅落留痕日志、零告警；无登记的 run 零新增开销（登记文件缺省不存在即跳过）。
- 拷回留痕：result-bearing run 结束时登记文件拷回主树 `.fenix/host_changes/<spec>.json`（per-spec 文件防并发互覆）；主树已有较新留痕时，不被 worktree 陈旧登记回灌覆盖。
- 解析容忍（fail-open）：登记文件缺失、非法 JSON、顶层非列表、元素非 dict、缺对象路径均按无有效登记处理——派发侧零告警零异常，混合清单只统计有效元素；空数组是合法值（与缺失可区分）；`{changes: [...]}` 包装形态容忍；`host_change_object_path` 兼容 `path` 别名、`object_path` 优先。
- 汇总校验：run-result 的 `host_changes` 字段为警告级 fail-open 校验——字段缺失零拦截零告警（历史 run 与无宿主变更 run 零开销），汇总与登记对象路径集合不一致仅 WARNING 放行，不产生失败终态、不参与门判定。
- administrator 处置记录模板：凡破坏性动作（删除/覆盖/状态重置/进程重启/宿主系统级变更）对应条目 MUST 写明备份目录与回滚计划（原版本位置+版本+还原步骤），未先备份即动手属处置违规；备份目录与回滚计划为必填项，不得仅作示例性提及。

## 关键行为

- 终态记录点时序：读取 worktree 根登记文件 → 失败终态派发告警 → worktree 清理；读取发生在清理之前，保证击杀场景登记仍可读。
- 派发与解析收口在 admin_store 派发方法与 runner/result_gate 的登记解析单点，admin_store 只做存储与派发，不自行感知 run 终态。

## 溯源

- 2026-10-13 evo-add-host-change-governance（spec/archive/2026-10-13-evo-add-host-change-governance） — 新增宿主系统级变更备份与即时登记契约（登记文件为权威载体）、失败终态含击杀类的回滚义务告警派发与去重、成功终态留痕、登记拷回主树留痕、解析与汇总校验 fail-open、administrator 破坏性动作 MUST 项
