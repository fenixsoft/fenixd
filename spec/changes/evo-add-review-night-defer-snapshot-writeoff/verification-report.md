# 验证报告：evo-add-review-night-defer-snapshot-writeoff

> ⚠️ 本报告由框架于 2026-10-10T17:57:14Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-10T17:57:14.155248+00:00+run-result@mtime1791655034194234502

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.14M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| night-window-multi-parse-probe | 多窗静默窗解析函数行为探针（独立于实现侧测试直打 core/code_fix.py:3096 _parse_night_quiet_windows）：多窗逗号分隔解析为两段 (start_min,end_min,text)；分号分隔+首尾空格同样解析；单窗薄包装 _parse_night_quiet_window（:3126）对 '04:15-04:45' 返回 (255,285,'04:15-04:45') 与多窗化前逐字节一致；缺省常量文本仍为 '04:15-04:45'（:3066）；空串/off/OFF 禁用返回 None；混合非法片段（合法段+bad 段）整体返回 None 宁缺毋错；end<=start 含相等逆序非法；空段 '04:15-04:45,,' 非法；小时越界 '24:00-25:00' 非法 | pass | 0/10 | - |
| night-window-multi-gate-pytest | code-fix 守卫多窗化 pytest 套件全绿（deliverable tests/test_code_fix_night_quiet_window.py，34 例）：多窗命中第二窗取该窗末、多窗同中取最晚 end、两窗之间空档照常放行、同日两窗各自武装一次（窗次幂等键含窗文本）、同窗次不重复武装、单窗配置行为逐字节一致、单窗解析不变、分号+空格多窗解析、混合非法片段整体无窗、混合非法窗内时刻放行且 WARNING 一次、code-fix 侧预计跨窗顺延与窗末释放（TestPredictedCrossWindow）。断言用例名来自实测输出行 | pass | 0/13 | - |
| night-window-admin-avoid-probe | admin 唤起避让多窗化行为探针（core/admin_monitor.py:5594 _night_dispatch_block_reasons，经 object.__new__ 最小装配直打）：多窗配置 04:20 命中第二窗返回避让原因且短语含命中窗区间 04:15-04:45；03:30 落两窗之间空档不避让；单窗配置 '04:15-04:45' 命中行为与多窗化前一致；off 禁用不避让；混合非法片段整体无窗不避让（配置异常按无窗处理不阻断唤起主路径） | pass | 0/7 | - |
| review-night-defer-behavior-probe | 周期审查跨窗顺延判定行为探针（core/admin_monitor.py:1846 _code_review_night_window_defer_note 与 :1906 _pending_writeoff_note，经 object.__new__ 最小装配直打）：3 轮归档 duration_s=7800s 样本下 01:00 派发预计区间 01:00-03:10 与多窗之一相交即顺延，note 含预计区间/窗区间/「同日防重未写」文案；双窗同中取最晚窗末（note 同时含两窗文本）；无样本时 01:00 不落窗不顺延（回退仅判派发时刻）、03:05 落窗顺延且标注「派发时刻」；归档损坏行降级为无样本；恰压线（预计结束==窗起点）视作不相交照常派发；00:00+130min 不及 03:00 照常派发；pending-writeoff 标注：无锚返回空串、有锚返回「，部分覆盖待核销（run_id=…）」 | pass | 0/13 | - |
| review-night-defer-pytest | 周期审查跨窗顺延 pytest 套件全绿（deliverable tests/test_code_review_night_defer.py，10 例）：预计区间压窗时 reason=night_quiet_window_deferred 且同日防重状态未写、单飞标志已复位；最近 3 轮样本窗口；多窗相交取最晚窗末；窗内外回退两向；缺 duration_s 字段样本剔除；短 run 照常派发；恰压窗起点派发；归档损坏行与取样异常降级不阻断派发。断言用例名来自实测输出行 | pass | 0/11 | - |
| salvage-writeoff-anchor-probe | pending-writeoff 锚读写清行为探针（core/code_review.py:1549-1580，独立于实现侧测试直打）：锚文件名为 writeoff-pending.json（台账目录）；无锚时读取返回空 dict（=无待核销现场）；写入 {run_id,inserted,updated,at} 后读回一致；覆盖写后只留最新一次现场（run_id=code-review-2 顶掉 code-review-1）；清除后读取回到空 dict；对已清除锚重复清除幂等不抛错 | pass | 0/7 | - |
| salvage-writeoff-pytest | salvage 待核销锚与 scheduled 全仓核销 pytest 套件全绿（deliverable tests/test_code_review_salvage_writeoff.py，12 例）：error 收场抢救 inserted>0 写锚并 upsert 台账；覆盖写顶旧锚；零行抢救不写锚；error 收场绝不核销既有 open（红线）；scheduled 全仓 run 覆盖完整解锁核销 （resolved>0）并清锚；agent 静默少审（累计覆盖不全）核销锁定且 open 不动；无锚时完整覆盖收尾清锚幂等；窗口档 scheduled 与 manual_window 绝不核销；完成日志有锚追加待核销标注、无锚不标注。断言用例名来自实测输出行 | pass | 0/13 | - |
| salvage-source-contract-probe | 源码契约探针（tasks 4.4「MUST NOT 静默放宽契约」的独立复核）：maintenance_runs.py 零 night_quiet_window 字样（顺延判定不进收尾模块）；核销资格放宽条件文本 'review_kind == "scheduled" and window_start is None' 在场且既有 manual_full 资格保持；窗口档「只增不核销」与 error 收场「绝不核销」红线注释固定在场；_writeoff_coverage_guard 仍在解锁链（宁锁勿白洗）；锚写/清调用均在收尾模块；admin_monitor 完成日志读锚（read_pending_writeoff）与「部分覆盖待核销」标注文案在场；顺延分支行序先于 compute_window/同日防重 save_code_review_state（副作用前移约束）；顺延分支内复位单飞标志 | pass | 0/10 | - |
| regression-affected-contract-suites | 回归点：本 SPEC 改写的四个模块（code_fix/admin_monitor/code_review/maintenance_runs）波及的既有契约面测试套件全绿（实现者声明的 8 个受影响区域对应 9 个测试文件：dispatch_window_avoidance/review_decoupling/run_at/scope_config/provider_failover/severity_gate/failure_registration_closeout/code_review/code_fix）。退出码 0 仲裁全部通过；输出含 'passed in' 确认套件正常收尾 | pass | 0/2 | - |
| full-suite-collect-zero-error | 回归点：全仓测试收集零错误（pytest --collect-only -q，实现者声明 8207+ 例收集零错误）。收集期 import 错误/夹具装配错误会让 pytest 退出码非 0 或输出 errors——以退出码 0 + 'tests collected in' 仲裁。修复注记：8246 例用例 ID 行使输出远超引擎 64KB stdout 捕获窗口，摘要行被截掉致断言必失败；命令改为全量落盘 .history/collect-full-suite.txt 后 stdout 仅回显尾 5 行（tail -5），exit_code 经 exit $ec 传回 pytest 真实退出码，两条断言均原样保留未弱化 | pass | 0/2 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

