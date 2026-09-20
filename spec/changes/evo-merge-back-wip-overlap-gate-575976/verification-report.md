# 验证报告：evo-merge-back-wip-overlap-gate-575976

> ⚠️ 本报告由框架于 2026-09-18T00:25:10Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-18T00:25:10.363806+00:00

## 结论：✅ 通过（verified）

**状态：verified — 13/13 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 13/13 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 13 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 23.84M |
| 本链增量 Token（输出） | 0.10M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| merge-gate-block-policy-zero-pollution | 功能点 1.1（tasks 2.1）：WIP 重叠 + 显式阻塞策略 → merge-back 中止、返回可区分的 wip_gate_blocked=True 失败、主树零污染（不 stash/不 merge/不 pop、无文件被丢弃、HEAD 不推进、工作区保持可写） | pass | 0/3 | - |
| merge-gate-auto-stash-preserve-and-recover | 功能点 1.1/1.4（tasks 2.2）：默认自动收纳策略——重叠改动随闸门前缀 stash 卷走、merge 成功；pop 冲突时条目保留在栈（git show stash@{0}:core/a.py 可找回 WIP 内容）；非重叠 WIP（不同 hunk）merge 后恢复、无 UU 半合并残留 | pass | 0/4 | - |
| merge-gate-scope-excludes-spec-changes | 功能点 1.2（tasks 2.3）：闸门作用域排除 spec/changes/**——仅该前缀重叠（即使显式配置 block）不阻塞、不收纳、不新增 stash，沿用既有提交通道收口 | pass | 0/2 | - |
| merge-gate-no-overlap-regression | 功能点回归（tasks 2.4）：无重叠 / 主树干净 → 即使配置 block 策略也逐字节现行行为（merge 成功、主树干净、零 stash）；主树干净时闸门零介入零 WARNING | pass | 0/3 | - |
| merge-gate-stash-prefix-isolation | 功能点 1.3（tasks 1.3）：闸门收纳前缀 WIP_GATE_STASH_PREFIX 与 AUTOSTASH_MSG_PREFIX 隔离（reclaim_stale_autostash 按子串匹配栈顶，复用会让故意保留条目被 60s 巡检抢走）；端到端：干净 pop 不误删条目、闸门前缀条目留在栈中 | pass | 0/3 | - |
| wip-overlap-precheck-regression | 回归（tasks 2.6 子集）：既有 WIP 重叠预检语义不被闸门破坏——相交预警且不阻断（MergeConflictInfo.wip_overlap 非空）、无交集静默、主树干净零开销 | pass | 0/4 | - |
| dispatch-block-bypasses-breaker-and-alerts | 功能点 1.5/1.6/1.7（tasks 2.5）：阻塞路径旁路熔断 + 告警直发——wip_gate_blocked=True 跳过 _merge_fp/_merge_streak 记账、spec 保持 in-flight 不 transition blocked；admin_alerts 落 handled=false 的 mergeback_wip_overlap 记录（description 含重叠清单与找回命令、evidence 序列化为 str）；连续两次阻塞恒不记账；repair re-merge 站点同样旁路 | pass | 0/6 | - |
| merge-gate-self-fault-degrade | 功能点 1.10（tasks 1.10）：闸门自身异常（git 命令失败/超时）退化为现行行为——不阻塞、不新增 stash、不误拦合并（静态核对 _detect_wip_overlap 捕获 TimeoutExpired/OSError 返回空列表、_wip_gate_policy 缺省回退 auto） | pass | 0/2 | - |
| admin-monitor-whitelist-and-frontend-label | 功能点 1.8/1.9 + 三站点覆盖（tasks 1.8/1.9/1.5）：mergeback_wip_overlap 收录 STORED_SIGNAL_TYPES 白名单（未收录则摄取循环跳过、告警石沉大海）、SIGNAL_SEVERITY=major、SIGNAL_RECOMMENDATION 含核对指引；dispatch 三个 merge 结果处理站点均覆盖 wip_gate_blocked 旁路；前端 SIGNAL_LABEL 新增「合并被主树改动阻塞」映射 | pass | 0/4 | - |
| regression-suites-all-green | 功能点 2.6（tasks 2.6）：回归套件全绿——test_worktree_merge_guard（闸门新用例 + 既有 guard/dist 自愈/_drop_superseded_stash_entry 判定）、test_pm_engine_dispatch_fixes（告警/熔断既有语义）、test_worktree_stray_and_identical（stash 栈与 pop 恢复语义不破坏） | pass | 0/2 | - |
| seed-mergeback-overlap-alert-fixture | 验证数据供给：经真实 AdminStore.append 向夹具项目 /root/scheduling-showcase/.fenix/admin_alerts.json 写入 mergeback_wip_overlap 的 escalation（handled=false、major、description 镜像 _report_mergeback_wip_overlap 文案：重叠清单/找回命令/处置指引）与 disposition（signal_type=mergeback_wip_overlap、result=resolved）记录，供 api/web 场景经 depends_on 消费（状态经被测应用 dashboard 传递）；幂等：先移除携带标记 verify-fixture-mergeback-gate-575976 的旧记录 | pass | 0/2 | - |
| api-alerts-surfaces-mergeback-overlap | HTTP 端到端（api 场景，治理铁律）：GET /api/alerts?project=scheduling-showcase 响应含本次 seed 的 mergeback_wip_overlap escalation（signal_type/handled=false/severity major、description 含重叠清单与 git stash list 找回命令、evidence 为字符串）；GET /api/admin-activities?project=scheduling-showcase 响应含 disposition 记录。URL origin 由框架改写（BASE_URL 注入） | pass | 0/11 | - |
| web-activities-renders-mergeback-overlap-label | 前端收口（功能点 1.9 可视化面）：运维记录页（SPA hash 路由 #/activities）自动运维视图渲染 seed 的 disposition 卡片（data-testid=activity-card 内 signalTag 按 SIGNAL_LABEL 渲染「合并被主树改动阻塞」紫标），视图切换控件在位、零 console/网络错误 | pass | 0/6 | - |

## 本轮场景集变更

当前稳定场景集共 13 个（第 1 轮）。

- 首轮写入 13 个场景

