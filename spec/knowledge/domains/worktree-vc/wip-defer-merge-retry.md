# spec 车道 WIP 阻断延迟合回

<!-- knowledge: capability=wip-defer-merge-retry rev=1
     sources=spec/archive/2026-10-02-evo-add-wip-defer-merge-retry-consumer -->

spec 实现车道合回被主树 WIP 重叠闸门拦截后的「等待-自动合回」周期：拦截即落结构化等待标志，daemon 周期复查、主树清干净后自动 merge-only 合回，超限降级人工——「WIP 清了自动合回」是默认路径，admin 只处理真冲突与超限降级。

## 规则

### 等待载体

- 合回被 WIP 重叠闸门拦截时，阻断处理在同一次 `update_spec` 里落结构化等待标志：`_wip_gate_deferred=True` + 重试计数（复用 `_merge_retry_count`）+ 首阻时刻（`_merge_retry_first_at`，同 spec 再次阻断沿用不重置）；error 文本只作取证补充，MUST NOT 是唯一现场标志。标志登记进 STATE.md 布尔往返清单，重启不丢。
- dispatch 主链、fast-track、repair 车道三处同型阻断站点共用该落载体路径，自动受益。
- 落标志即确立生命周期不变式：`implementing` 且带标志 ⇒ 该 spec 无在飞实现 run（触发阻断的 run 已收尾，新 run 只能自 ready 派发而两个 boot 复位写点已清标志）。周期消费者凭此不变式免查活动 run，不在消费者内再做存活探测。

### 周期自动合回

- daemon 主循环以 120 秒节拍的独立计时器复查带标志条目（try/except 包裹不中断主循环；节拍为代码常量，非配置键，无 Dashboard 配置义务），节拍先于 admin 5 分钟巡检。
- 复查仅认「status=implementing 且 `_wip_gate_deferred` 为真」的条目，逐条在主树锁内执行 merge-only 重试（不重跑实现轮）。成功走既有成功收尾：推进 implemented、verifier 入队、等待标志与顺延记账清账，并把原 `mergeback_wip_overlap` major 告警写 `result=resolved` 处置记录显式闭环（stuck-signal 闭环范式）。
- 状态守卫拆两层、禁并成单条「须带 wip 标志才放行」：既有 merge-only 重试入口 `_retry_merge_back_only` 只拦 status≠implementing——人工/admin 已合并推进的条目跳过合并并清账（标志/计数/首阻全清、状态不改写），杜绝迟到重试重复合并；「implementing+带标志」的严格筛选放在周期扫描层，保证既有 spec 目录顺延链（条目只带 `_merge_retry_pending`）不受影响。
- 重试仍被 WIP 阻断：计数 +1、首阻时刻沿用、状态保持 implementing、标志保留、error 叠加 deferred 取证形态；拦截不记账不变式延续——MUST NOT 落指纹熔断记账、不误冻结 spec。
- 重试落非 WIP 失败（真内容冲突等）：等待到此结束——先清等待标志再交回既有可重试/真失败通道，MUST NOT 尝试自动解决内容冲突；该清账同时杜绝陈旧标志在恢复 run 在飞期间触发过早合并。

### 有界与降级

- 预算双门先到为准：自首阻起超过 90 分钟（`WIP_DEFER_WINDOW_MINUTES`）或重试达 6 次（`WIP_DEFER_MAX_ROUNDS`，对齐 code-fix defer 范式）。常量单源定义于 dispatch queue，admin 监视器 MUST 导入同一常量，禁两处独立阈值口径。
- 超限即停止自动重试，发 `mergeback_wip_defer_stuck` major 人工处置告警；现场标志保留供人工取证；同条目降级在 daemon 生命周期内至多一次，不重复降级。

### 先于孤儿探测

- 消费者节拍（120 秒）远短于 `orphaned_state` 缺省阈值（15 分钟），自动合回先于孤儿探测生效。
- 等待期内（未超轮数与窗口上限）`orphaned_state` 探测豁免带标志的 implementing 悬置条目（与 `_repair_awaiting_remerge` 豁免同型）；超限降级后豁免自动失效，孤儿探测恢复兜底，与降级告警汇合指向人工。

### 标志清账写点

- 等待标志在三类写点同步清除：合并成功清账块、boot 保留续做复位写点（implementing→ready）、boot 清空重建复位写点。漏清保留续做写点的失效形态最贵：重启后陈旧标志会在恢复 run 在飞期间把半成品分支过早合入主树，并与在飞 run 收尾竞态。

### 车道边界与已知代价

- 本能力属 spec 实现车道（STATE.md 标志 + daemon 周期消费者）；code-fix 修复批的延迟合回走独立台账（fix-deferred.json + 链边界消费者），两车道互不消费对方载体，仅预算参数范式对齐（90 分钟/6 次）。
- 等待计数与 spec 目录在飞顺延共用同一套记账字段：同一 spec 先后经历两种阻断时窗口/轮数混合累计，wip 降级预算可能被顺延轮数加速消耗。两预算均有界（90 分钟/6 次与 30 分钟/3 次），该混账为已知接受代价，不引入第二套计数。

## 溯源

- 2026-10-02 evo-add-wip-defer-merge-retry-consumer（spec/archive/2026-10-02-evo-add-wip-defer-merge-retry-consumer） — 新建本页：WIP 阻断落结构化等待标志（STATE.md 往返 + 三类清账写点）、daemon 120 秒周期消费者（主树锁内 merge-only 重试、成功收尾告警闭环、两层状态守卫）、90 分钟/6 次预算双门降级（`mergeback_wip_defer_stuck`）、orphaned_state 等待期豁免与超限失效
