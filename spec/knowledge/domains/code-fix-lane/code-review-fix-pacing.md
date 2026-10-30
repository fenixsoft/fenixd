# 审查发现分级修复节奏（severity 门限与周批）

<!-- knowledge: capability=code-review-fix-pacing rev=1
     sources=spec/archive/2026-10-30-evo-add-codefix-severity-batch-gate -->

控制 code-review 台账 open 发现进入修复批的节奏：severity 达门限的当日修，低于门限的挂起累积到周批统一处理，防止纯 minor/info 发现逐日触发完整修复流水线形成自我供料循环。

## 规则

- **总开关**：`admin.code_review_fix.severity_batch_gate_enabled`（严格 bool，缺省 `false`）。关闭＝分级门限与周批整体旁路，全部 open 发现当日处置、不挂起不累积；非 bool 值视同关闭。门限生效值经单一入口 `severity_gate_from_config_segment` 解析，关闭即返回空门限，各谓词恒放行。
- **门限参数**：`min_immediate_severity` 缺省 `major`，限 severity 词表四档 `critical | major | minor | info`，词表外取值（含历史漂移值域 high/medium/low，配置侧不做归一）回退缺省并告警；`minor_batch_cadence` 缺省 `7`（天），正整数，非法回退缺省并告警。配置异常一律回退缺省、不阻断评审与修复主链。
- **分流**：severity 档位序 `info < minor < major < critical`。达 `min_immediate_severity` 的条目保持既有当日批序（first_seen_at 升序不变）；低于门限的 code-review 来源条目挂起延后。`regression-` 前缀条目（回归来源）豁免门限，恒当日处置，未知档位规则亦不作用于该来源；code-review 来源的未知/缺失档位按低于门限挂起（fail-open）并告警。
- **挂起标记**：低于门限条目随台账落账维护 `severity_deferred` / `severity_deferred_since` 两字段；周批窗口以首个挂起锚起算，同指纹重复发现不重置锚；存量条目锚缺位回退 `first_seen_at`。挂起条目保持 `open` 状态。
- **周批组放行**：open 挂起集中最早锚距今达 `minor_batch_cadence` 天时，累积的全部低于门限条目整组进入当批（非逐条到期逐条放行）；窗口判定仅在 open 池上进行，resolved/ignored 条目的残留锚不参与。
- **双入口同门**：候选筛选（generate_fix_spec）与选批（select_batch、链末批判定、checkpoint）导入 `code_review.py` 同一谓词函数族共用同门；Dashboard 手工触发不可绕过——未到周批窗口对纯 minor/info 的 open 集合触发修复批，按空批处理（条目计入 skipped、原因 `severity_deferred` 并说明原因），不生成 SPEC。
- **升档晋级**：同指纹重复发现沿既有台账 upsert 合并（刷新 last_seen_at/severity 等可变字段），分级门限不新增重复立项路径；severity 被刷到达门限档位即按当日批处置并清挂起标记；条目立项（in_spec）与核销（resolved）时清挂起标记。
- **链收敛对账**：挂起条目不计为 skipped/lost。选批为空若因剩余 open 条目全部挂起所致，收敛落 `severity_deferred` 健康等待态（phase=idle），周批窗口到期后下一 checkpoint 自然放行整组重投；混合场景走既有分级文案并附挂起条数注记。挂起集与 select_batch 同池同排除（open 池，排除失败档案 ∪ 链内跳过 ∪ 延迟台账 ∪ 止损跳过集）。
- **台账独立**：severity 挂起标记（随台账条目）与 WIP-defer 延迟合回台账（fix-deferred.json / _deferred_item_ids / first_deferred_at）独立命名、独立载体、互不串写；挂起条目不进 exclude_ids——挂起是暂缓而非本链排除，周批窗口到期后自然回流可选池。

## 关键行为

- 总开关缺省关闭＝全部发现当天内容当天处理；重开门限后周批窗口仍以历史首个挂起锚起算（关闭期间读侧不消费残留标记，重开无需清场）。
- 门限配为最低档 `info` 时词表内条目恒达门限，行为与关闭门限等价（词表外档位仍按低于门限挂起），可作细粒度灰度回退。

## 溯源

- 2026-10-30 evo-add-codefix-severity-batch-gate（spec/archive/2026-10-30-evo-add-codefix-severity-batch-gate） — 新建本页：分级门限与周批节奏（两配置键、双入口同门、regression- 豁免、挂起标记与组放行、链收敛对账、配置回退缺省），附带运维收尾把用户级 admin.code_review.scope 回拨 window。
- 2026-10-11 主树修复提交 10f3bc048 — 总开关 severity_batch_gate_enabled 引入并缺省翻转（全部发现当天处理）；挂起集对账改与 select_batch 同池同排除，根治 resolved/ignored 残留锚致组放行误判、空批 blocked 误报「预算内失败」。
