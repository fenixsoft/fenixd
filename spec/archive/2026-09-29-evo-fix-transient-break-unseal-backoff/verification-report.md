# 验证报告：evo-fix-transient-break-unseal-backoff

> ⚠️ 本报告由框架于 2026-09-23T02:02:15Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-23T02:02:15.743425+00:00

## 结论：✅ 通过（verified）

**状态：verified — 13/13 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 13/13 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 13 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.66M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| unseal-config-keys-normalization | 配置规范化（tasks 1.4）：core/config.py get_transient_config 纳入 agents.transient_unseal_* 五键，缺省值为保守档 60/600/120/1800/30，非法值（小数/负数）回退缺省、自定义值接受、显式 0（禁用）保留 | pass | 0/2 | - |
| unseal-defaults-conservative-and-disable-switch | 缺省档与禁用开关（design D5）：ProviderCircuit 缺省 unseal 配置 = base 60s / cap 600s / 观察窗 120s / 稳定窗 1800s / 错峰节拍 30s；base=0 时到期即全量放行（既有语义）且不记忆解封次数 | pass | 0/3 | - |
| unseal-enters-hold-not-immediate-release | 解封不立即全量放行（spec：解封后渐进恢复而非立即全量放行）：熔断冷却到期后进入 post-unseal hold 而非 open，hold 期内单条准入被拒（积压整队持有）；含 tests/test_transient_backoff.py:780 修订后语义（清零保留、hold 先行） | pass | 0/3 | - |
| unseal-first-hold-equals-base | 首场解封 hold=基数而非 0（design D2 计数规则）：首次到期解封该指纹计数记 1，hold = 基数×1 = 60 秒 | pass | 0/2 | - |
| unseal-hold-scales-caps-multi-fingerprint | hold 随解封次数渐进且封顶（spec：hold 随解封次数渐进且封顶）：同指纹连续四场解封 hold 依次 30/60/90/100（30×4 触顶）；多指纹并存时 hold 取各指纹解封次数最大值 | pass | 0/3 | - |
| unseal-stable-window-decay-reset | 稳定后衰减复位（spec：稳定后衰减复位）：解封次数在稳定观察窗内无新熔断则逐窗减一至清零（非直接清零），衰减复位后下一场解封 hold 回到基数水平 | pass | 0/2 | - |
| unseal-probe-single-admission-staggered-release | 探针单条准入与错峰放行（spec：探针成功后错峰放行）：hold 期满仅放行恰好一条最高优先级派发作探针，同拍第二准入被拒；探针观察窗内无同指纹新记账则期满转入 release，其余积压按错峰节拍逐拍放行（无同拍全量）；积压放完退出错峰态恢复常态节奏 | pass | 0/3 | - |
| unseal-probe-failure-refreeze-bump | 探针失败重回冻结（spec：探针失败重回冻结，异常路径）：探针观察窗内同指纹新记账判败，按现行规则重新熔断且该指纹解封次数额外 +1（下一场 hold 相应加长至基数×3）；观察窗内非同指纹新记账不误判探针失败 | pass | 0/3 | - |
| unseal-dispatch-gate-order-and-drain | 派发闸门态序消费（tasks 1.2，design D3）：Dispatcher._process_queue 首道闸按 冻结 > post-unseal hold > 探针观察窗 > release-wait 态序短路，四态下积压条目均不得被 pop（整队持有）；release-wait 且队列空时通知退出错峰态（放完回调） | pass | 0/3 | - |
| unseal-self-drive-timer-no-external-trigger | 无外部触发仍能主动唤醒派发（tasks 1.1 / design D3，真实定时器端到端）：触发熔断后不做任何人为查询，仅靠 threading.Timer 定时器链自驱穿越 解封→hold→探针→错峰放行 全部到期锚点（回归 fix-provider-transient-backoff 之前惰性停摆缺口） | pass | 0/2 | - |
| unseal-config-hot-update | 配置键热更新生效（spec：配置键生效）：修改 agents.transient_unseal_backoff_base_seconds / probe_window_seconds 后，下一场 hold 与探针观察窗按新值生效（配置对象原地修改等价 30 秒热更新后的生效值） | pass | 0/2 | - |
| unseal-revised-expiry-wake-tests | 既有用例修订到新语义（tasks 2.2：tests/test_transient_backoff.py:866/:890）：到期唤醒恰一次且唤醒不等于放行（解封后先 hold、hold 期满放单条探针）；唤醒抛异常不阻断 解封→hold→探针 的闸门推进（fail-open，异常路径） | pass | 0/3 | - |
| unseal-existing-backoff-layers-regression | 既有退避层不受影响（spec：既有退避层不受影响，回归点）：tests/test_transient_backoff.py 全量 65 例通过——原地退避 30/60/120 序列解析、per-spec 600s 重派延迟 timer、指纹归一、4xx 非瞬断分类、关机守卫等既有三层退避语义零变化 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 13 个（第 1 轮）。

- 首轮写入 13 个场景

